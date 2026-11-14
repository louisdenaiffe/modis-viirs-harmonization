"""Independent hold-out validation of the MODIS -> VIIRS calibration models (owner: C, SCHEMA §7).

Independence rule: only ``MODELS``, ``fit_model`` and ``apply_model`` are imported from
``harmonize.calibrate``. Folds, out-of-fold (OOF) predictions and scores are all computed
here; B's fit statistics, stability tables and recommendation are never read.

Hold-out schemes (each yields exactly one OOF prediction per row; the test masks partition
the rows of every (modis_source, daynight) table):

* ``leave_domain_out`` (primary) one fold per ``domain`` (country / file label). Every row
                       of the held-out domain is predicted by a model that never saw that
                       domain, i.e. transfer to an unseen region.
* ``spatial_block``    10 deg x 10 deg blocks, grouped K-fold (K = ``N_BLOCK_FOLDS``,
                       greedy size-balanced, deterministic). Transfer across space that
                       ignores political borders (a big country spans several blocks).
* ``leave_year_out``   one fold per year (only when >= 2 years are present).
* ``lomo``             leave-one-month-of-year-out: the fold is the calendar month (all
                       years, all domains), so a held-out July is never seen in any year.
                       This tests seasonal transfer and is stricter than leaving out a
                       single ``YYYY-MM``.

Evaluation mode is **back-cast**: the model is only applied to rows where the MODIS-side
metric is > 0 (prediction 0 elsewhere) and compared with *all* VIIRS, VIIRS-only cells
included. In a year without VIIRS the VIIRS-only cells do not exist, so this is the error a
real back-cast makes.

Scores, for each scheme x metric x model x modis_source x daynight:

per domain-year (table ``domain_scores``)
    ``bias_pct``     100 * (sum pred - sum VIIRS) / sum VIIRS over the domain-year
    ``r2_monthly``   R^2 (1 - SS_res/SS_tot, can be < 0) of the monthly totals
    ``spearman_monthly`` rank correlation of the monthly totals
distribution across domain-years (table ``scores``)
    ``median_abs_bias_pct``, ``p90_abs_bias_pct``, ``max_abs_bias_pct``,
    ``pooled_bias_pct`` (all domain-years summed), ``median_r2_monthly``,
    ``median_spearman_monthly``, ``global_r2_monthly`` (R^2 of the summed-over-domains
    monthly series).

Baselines: ``raw_modis`` (VIIRS = MODIS) and ``ratio_global``. ``summary`` ranks every
metric+model under leave-domain-out by the 90th percentile of |domain-year bias| (then the
worst case, then the median monthly R^2). Bias in % is scale-free, so the ranking also
answers "which metric should be harmonized".

Efficiency: per (modis_source, daynight) table the folds are built once, each training
frame is sliced once per fold and reused for every metric and model, the model is applied
only to the test rows with MODIS > 0, and OOF predictions are reduced to
domain x year x month totals with ``np.bincount``. Nothing is subsampled.
"""
from __future__ import annotations

import inspect
import time
import warnings
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import DAYNIGHT, METRICS, MODIS_CONFIGS, Config

BASELINE_RAW = "raw_modis"
BASELINE_RATIO = "ratio_global"
SCHEMES = ("leave_domain_out", "spatial_block", "leave_year_out", "lomo")
PRIMARY_SCHEME = "leave_domain_out"
BLOCK_DEG = 10.0
N_BLOCK_FOLDS = 5
# MODIS-side feature columns (paired table ``modis_<f>``) that a model may use at apply time
MODIS_FEATURES = ("frp_mean", "frp_p90", "scan_mean", "bright_mir_mean", "n_terra", "n_aqua")
# extra key columns handed to models alongside the MODIS-side values (never a VIIRS column)
ROW_KEYS = ("cell_id", "cell_lat", "cell_lon", "period", "period_start", "daynight", "domain")


# ============================================================== model backend
# Local stand-in implementing B's v2 interface; used only while harmonize.calibrate does not
# expose it. ratio_regional here is a single-level 10 deg tile ratio with pseudo-count
# shrinkage to the global ratio (B's real model is nested and empirical-Bayes).
_STUB_TILE_DEG = 10.0
_STUB_PSEUDO = 200.0      # pseudo-count in MODIS units pulling a tile's k toward global


def _stub_fit(name: str, paired: pd.DataFrame, metric: str, cfg: Config) -> dict:
    x = paired[f"modis_{metric}"].to_numpy(float)
    y = paired[f"viirs_{metric}"].to_numpy(float)
    kg = float(y.sum() / x.sum()) if x.sum() > 0 else 1.0
    if name == "ratio_global":
        return {"model": name, "k": kg}
    if name == "ratio_regional":
        t = _tile_key(paired["cell_lat"].to_numpy(float), paired["cell_lon"].to_numpy(float),
                      _STUB_TILE_DEG)
        sx = pd.Series(x).groupby(t).sum()
        sy = pd.Series(y).groupby(t).sum()
        k = (sy + _STUB_PSEUDO * kg) / (sx + _STUB_PSEUDO)
        return {"model": name, "k_global": kg, "tile_deg": _STUB_TILE_DEG,
                "k_tile": {str(int(i)): float(v) for i, v in k.items()}}
    raise ValueError(f"stub has no model {name!r}")


def _stub_apply(params: dict, modis_rows: pd.DataFrame, metric: str) -> np.ndarray:
    x = np.nan_to_num(modis_rows[metric].to_numpy(float))
    if params["model"] == "ratio_global":
        return np.maximum(params["k"] * x, 0.0)
    t = _tile_key(modis_rows["cell_lat"].to_numpy(float), modis_rows["cell_lon"].to_numpy(float),
                  params["tile_deg"])
    lut = {int(i): v for i, v in params["k_tile"].items()}
    k = pd.Series(t).map(lut).fillna(params["k_global"]).to_numpy(float)
    return np.maximum(k * x, 0.0)


def get_backend() -> tuple[list[str], Callable, Callable, str]:
    """Return (model_names, fit_fn, apply_fn, backend_label).

    Uses harmonize.calibrate when it exposes the v2 interface
    ``fit_model(name, paired, metric, cfg)``; otherwise the local stub.
    """
    try:
        from . import calibrate as cal  # noqa: WPS433
        params = list(inspect.signature(cal.fit_model).parameters)
        names = list(cal.MODELS.keys()) if isinstance(cal.MODELS, dict) else list(cal.MODELS)
        if len(params) >= 4 and params[1] in ("paired", "df", "data") and BASELINE_RATIO in names:
            return names, cal.fit_model, cal.apply_model, "harmonize.calibrate"
    except Exception:  # noqa: BLE001 - any import/signature problem -> stub
        pass
    warnings.warn("harmonize.calibrate does not expose the v2 model interface yet; "
                  "validating the local stub models (ratio_global, ratio_regional)")
    return ["ratio_global", "ratio_regional"], _stub_fit, _stub_apply, "stub"


def modis_rows(paired: pd.DataFrame, modis_source: str) -> pd.DataFrame:
    """MODIS-side view of a paired table, shaped like SCHEMA §3 rows: ``modis_`` prefix
    stripped, keys kept, ``source`` = the MODIS configuration. No VIIRS column."""
    cols = {c: c[len("modis_"):] for c in paired.columns
            if c.startswith("modis_") and c != "modis_source"}
    out = paired[[c for c in ROW_KEYS if c in paired.columns] + list(cols)].rename(columns=cols)
    out["source"] = modis_source
    return out


# ============================================================== folds
def _tile_key(lat: np.ndarray, lon: np.ndarray, deg: float) -> np.ndarray:
    iy = np.floor((np.asarray(lat, float) + 90.0) / deg).astype(np.int64)
    ix = np.floor((np.asarray(lon, float) + 180.0) / deg).astype(np.int64)
    return iy * 100_000 + ix


def year_of(df: pd.DataFrame) -> np.ndarray:
    if "year" in df.columns:
        return df["year"].to_numpy().astype(np.int64)
    return df["period"].astype(str).str[:4].astype(int).to_numpy()


def month_of(df: pd.DataFrame) -> np.ndarray:
    return df["period"].astype(str).str[5:7].astype(int).to_numpy()


def block_of(df: pd.DataFrame, deg: float = BLOCK_DEG) -> np.ndarray:
    return _tile_key(df["cell_lat"].to_numpy(float), df["cell_lon"].to_numpy(float), deg)


def _balanced_group_folds(groups: np.ndarray, k: int) -> np.ndarray:
    """Greedy size-balanced assignment of groups to k folds (largest group first, ties by
    group key, so it is deterministic and independent of row order)."""
    u, cnt = np.unique(groups, return_counts=True)
    order = sorted(range(len(u)), key=lambda i: (-cnt[i], u[i]))
    load = np.zeros(k, np.int64)
    fold_of = {}
    for i in order:
        f = int(np.argmin(load))
        fold_of[u[i]] = f
        load[f] += cnt[i]
    return pd.Series(groups).map(fold_of).to_numpy()


def make_folds(df: pd.DataFrame, scheme: str, n_block_folds: int = N_BLOCK_FOLDS,
               block_deg: float = BLOCK_DEG) -> list[tuple[str, np.ndarray]]:
    """Return [(fold_name, test_mask)]; train = ~test_mask. Test masks partition the rows.
    Returns [] when the scheme is not applicable (fewer than 2 groups)."""
    if scheme == "leave_domain_out":
        g = df["domain"].astype(str).to_numpy()
    elif scheme == "leave_year_out":
        g = year_of(df)
    elif scheme == "lomo":
        g = month_of(df)
    elif scheme == "spatial_block":
        b = block_of(df, block_deg)
        nb = len(np.unique(b))
        if nb < 2:
            return []
        f = _balanced_group_folds(b, min(n_block_folds, nb))
        return [(f"blockfold{k}", f == k) for k in range(min(n_block_folds, nb))]
    else:
        raise ValueError(f"unknown scheme {scheme!r}")
    u = np.unique(g)
    if len(u) < 2:
        return []
    return [(str(v), g == v) for v in u]


# ============================================================== scores
def _r2(obs, pred) -> float:
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    if len(obs) < 2:
        return np.nan
    sst = np.sum((obs - obs.mean()) ** 2)
    return float(1 - np.sum((obs - pred) ** 2) / sst) if sst > 0 else np.nan


def _spearman(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return np.nan
    return float(spearmanr(a, b).statistic)


def _bias(pred_sum, obs_sum) -> float:
    return float(100 * (pred_sum - obs_sum) / obs_sum) if obs_sum > 0 else np.nan


def score_domain_years(m: pd.DataFrame) -> pd.DataFrame:
    """``m``: monthly totals with columns domain, year, month, obs, pred. Returns one row
    per domain-year: obs_total, pred_total, bias_pct, r2_monthly, spearman_monthly."""
    out = []
    for (dom, yr), g in m.groupby(["domain", "year"], sort=True):
        g = g.sort_values("month")
        o, p = g["obs"].to_numpy(float), g["pred"].to_numpy(float)
        out.append(dict(domain=dom, year=int(yr), n_months=len(g), obs_total=o.sum(),
                        pred_total=p.sum(), bias_pct=_bias(p.sum(), o.sum()),
                        r2_monthly=_r2(o, p), spearman_monthly=_spearman(o, p)))
    return pd.DataFrame(out)


def distribution(ds: pd.DataFrame, m: pd.DataFrame) -> dict:
    """Distribution of domain-year scores + pooled global numbers."""
    ab = ds["bias_pct"].abs().dropna()
    gm = m.groupby(["year", "month"])[["obs", "pred"]].sum()
    return {
        "n_domain_years": int(len(ab)),
        "median_abs_bias_pct": float(ab.median()) if len(ab) else np.nan,
        "p90_abs_bias_pct": float(np.percentile(ab, 90)) if len(ab) else np.nan,
        "max_abs_bias_pct": float(ab.max()) if len(ab) else np.nan,
        "worst_domain_year": (f"{ds.loc[ab.idxmax(), 'domain']}-{ds.loc[ab.idxmax(), 'year']}"
                              if len(ab) else ""),
        "pooled_bias_pct": _bias(m["pred"].sum(), m["obs"].sum()),
        "median_r2_monthly": float(ds["r2_monthly"].median()),
        "min_r2_monthly": float(ds["r2_monthly"].min()),
        "median_spearman_monthly": float(ds["spearman_monthly"].median()),
        "global_r2_monthly": _r2(gm["obs"], gm["pred"]),
    }


# ============================================================== core loop
def _group_codes(d: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    """Integer code per row for (domain, year, month) + the decoding table."""
    key = pd.DataFrame({"domain": d["domain"].astype(str).to_numpy(), "year": year_of(d),
                        "month": month_of(d)})
    g = key.groupby(["domain", "year", "month"], sort=True)
    codes = g.ngroup().to_numpy(np.int64)
    uniq = g.size().reset_index()[["domain", "year", "month"]]
    return codes, uniq


def _validate_table(d: pd.DataFrame, src: str, dn: str, model_list: list[str], metrics,
                    schemes, fit, apply, cfg: Config, log) -> tuple[list, list]:
    """All schemes / metrics / models on one (modis_source, daynight) table.
    Returns (monthly frames, fold-info rows)."""
    rows = modis_rows(d, src)
    codes, keys = _group_codes(d)
    ng = len(keys)
    obs = {m: np.bincount(codes, d[f"viirs_{m}"].to_numpy(float), ng) for m in metrics}
    xs = {m: np.nan_to_num(d[f"modis_{m}"].to_numpy(float)) for m in metrics}
    monthly, finfo = [], []
    for scheme in schemes:
        folds = make_folds(d, scheme)
        if not folds:
            continue
        # oof[(metric, model)] = per-row prediction (0 where MODIS = 0)
        oof = {(m, mod): np.zeros(len(d)) for m in metrics for mod in model_list}
        nfail = {k: 0 for k in oof}
        t0 = time.time()
        for fname, test in folds:
            train = ~test
            finfo.append(dict(scheme=scheme, fold=fname, modis_source=src, daynight=dn,
                              n_train=int(train.sum()), n_test=int(test.sum()),
                              test_domains=";".join(sorted(map(str, d.loc[test, "domain"].unique())))))
            tr = d[train] if any(mod != BASELINE_RAW for mod in model_list) else None
            for m in metrics:
                te = test & (xs[m] > 0)
                if not te.any():
                    continue
                rte = rows[te]
                for mod in model_list:
                    if mod == BASELINE_RAW:
                        oof[(m, mod)][te] = xs[m][te]
                        continue
                    try:
                        params = fit(mod, tr, m, cfg)
                        p = np.asarray(apply(params, rte, m), float)
                        if p.shape != (int(te.sum()),):
                            raise ValueError(f"apply_model returned shape {p.shape}")
                        oof[(m, mod)][te] = p
                    except Exception as e:  # a failing model must not kill the run
                        nfail[(m, mod)] += 1
                        oof[(m, mod)][te] = np.nan
                        warnings.warn(f"{mod}/{m}/{src}/{dn}/{scheme}/{fname} failed: {e!r}")
        log(f"  {src:11s} {dn:3s} {scheme:16s} {len(folds):2d} folds  {time.time() - t0:6.1f}s")
        for (m, mod), pr in oof.items():
            bad = np.bincount(codes, np.isnan(pr).astype(float), ng) > 0
            ps = np.bincount(codes, np.nan_to_num(pr), ng)
            ps[bad] = np.nan
            mt = keys.copy()
            mt["obs"], mt["pred"], mt["raw_modis"] = obs[m], ps, np.bincount(codes, xs[m], ng)
            mt["scheme"], mt["metric"], mt["model"] = scheme, m, mod
            mt["modis_source"], mt["daynight"], mt["n_failed_folds"] = src, dn, nfail[(m, mod)]
            monthly.append(mt)
    return monthly, finfo


def run_validation(paired_by_source: dict[str, pd.DataFrame], cfg: Config, models=None,
                   schemes=SCHEMES, metrics=METRICS, sources=MODIS_CONFIGS,
                   daynights=DAYNIGHT, verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Evaluate metric x model x modis_source x daynight under every hold-out scheme.

    ``paired_by_source``: {modis_source: SCHEMA §4 paired table}. ``models``: subset of
    calibrate.MODELS (default all); the baselines raw_modis and ratio_global are always
    added. Returns {"scores", "domain_scores", "monthly_oof", "folds", "summary"} and
    writes each to ``cfg.out_dir / "validation" / <name>.csv``.
    """
    names, fit, apply, backend = get_backend()
    wanted = list(models) if models is not None else names
    model_list = [BASELINE_RAW, BASELINE_RATIO] + [m for m in wanted
                                                   if m not in (BASELINE_RAW, BASELINE_RATIO)]
    unknown = [m for m in model_list[1:] if m not in names]
    if unknown:
        warnings.warn(f"models not provided by the backend, skipped: {unknown}")
        model_list = [m for m in model_list if m not in unknown]
    log = print if verbose else (lambda *_: None)
    log(f"validation backend={backend} models={model_list}")
    monthly, finfo = [], []
    for src in sources:
        p = paired_by_source.get(src)
        if p is None or p.empty:
            continue
        for dn in daynights:
            d = p[p["daynight"] == dn].reset_index(drop=True)
            if d.empty:
                continue
            mo, fi = _validate_table(d, src, dn, model_list, metrics, schemes, fit, apply,
                                     cfg, log)
            monthly += mo
            finfo += fi
            del d
    mon = pd.concat(monthly, ignore_index=True) if monthly else pd.DataFrame()
    keys = ["scheme", "metric", "model", "modis_source", "daynight"]
    drows, srows = [], []
    if not mon.empty:
        for k, g in mon.groupby(keys, sort=False):
            ds = score_domain_years(g)
            tags = dict(zip(keys, k))
            drows.append(ds.assign(**tags))
            srows.append(dict(**tags, backend=backend,
                              n_failed_folds=int(g["n_failed_folds"].max()),
                              **distribution(ds, g)))
    dscores = pd.concat(drows, ignore_index=True) if drows else pd.DataFrame()
    if not dscores.empty:
        dscores = dscores[keys + [c for c in dscores.columns if c not in keys]]
    scores = pd.DataFrame(srows)
    res = {"scores": scores, "domain_scores": dscores, "monthly_oof": mon,
           "folds": pd.DataFrame(finfo), "summary": summarize(scores)}
    out = cfg.out_dir / "validation"
    out.mkdir(parents=True, exist_ok=True)
    for k, v in res.items():
        v.to_csv(out / f"{k}.csv", index=False)
    return res


def summarize(scores: pd.DataFrame) -> pd.DataFrame:
    """Ranking under the primary scheme (leave-domain-out; falls back to spatial_block when
    there is a single domain). Per (modis_source, daynight):

    * ``rank_in_metric``: models within a metric,
    * ``rank_overall``: metric+model combinations (raw_modis excluded),
    by p90 |domain-year bias|, then max |bias|, then -median monthly R^2. Also reports the
    worst p90 over all schemes (``worst_scheme_p90_abs_bias_pct``) as a robustness check."""
    if scores.empty:
        return scores
    prim = PRIMARY_SCHEME if (scores["scheme"] == PRIMARY_SCHEME).any() else "spatial_block"
    s = scores[scores["scheme"] == prim].copy()
    combo = ["metric", "model", "modis_source", "daynight"]
    worst = scores.groupby(combo)["p90_abs_bias_pct"].max().rename("worst_scheme_p90_abs_bias_pct")
    s = s.merge(worst.reset_index(), on=combo, how="left")
    s["_neg_r2"] = -s["median_r2_monthly"].fillna(-np.inf)
    sort = ["p90_abs_bias_pct", "max_abs_bias_pct", "_neg_r2"]
    s = s.sort_values(["modis_source", "daynight"] + sort, na_position="last")
    s["rank_in_metric"] = s.groupby(["modis_source", "daynight", "metric"]).cumcount() + 1
    cal = s["model"] != BASELINE_RAW
    s["rank_overall"] = np.nan
    s.loc[cal, "rank_overall"] = s[cal].groupby(["modis_source", "daynight"]).cumcount() + 1
    cols = ["scheme", "modis_source", "daynight", "metric", "model", "rank_overall",
            "rank_in_metric", "p90_abs_bias_pct", "median_abs_bias_pct", "max_abs_bias_pct",
            "worst_domain_year", "pooled_bias_pct", "median_r2_monthly", "min_r2_monthly",
            "median_spearman_monthly", "global_r2_monthly", "worst_scheme_p90_abs_bias_pct",
            "n_domain_years", "n_failed_folds", "backend"]
    return s[cols].reset_index(drop=True)


def best_combo(summary: pd.DataFrame, modis_source: str = "MODIS_ALL",
               daynight: str = "ALL") -> dict | None:
    """The rank-1 metric+model of ``summary`` for one source/daynight (my own evaluation)."""
    s = summary[(summary["modis_source"] == modis_source) & (summary["daynight"] == daynight)
                & (summary["rank_overall"] == 1)]
    return None if s.empty else s.iloc[0].to_dict()


if __name__ == "__main__":  # python -m harmonize.validate paired.parquet [out_dir]
    import sys
    path = sys.argv[1]
    df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(
        path, dtype={"cell_id": str, "period": str})
    cfg = Config(out_dir=sys.argv[2] if len(sys.argv) > 2 else "outputs")
    res = run_validation({s: g for s, g in df.groupby("modis_source", observed=True)}, cfg)
    pd.set_option("display.width", 220)
    print(res["summary"].query("daynight == 'ALL'").round(2).to_string())
