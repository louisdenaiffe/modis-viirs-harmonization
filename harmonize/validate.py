"""Independent hold-out validation of the MODIS -> VIIRS calibration models (owner: C).

Only `MODELS`, `fit_model` and `apply_model` are imported from `harmonize.calibrate`;
folds and scores are computed here, never read from B's `fit_stats`.

Schemes (every scheme yields exactly one out-of-fold (OOF) prediction per row, so
scores are computed on the pooled OOF predictions; per-fold spread is reported too):

* ``temporal_lomo``    leave-one-month-out (grouped by ``period[:7]``, so it also works
                       for ``time_step="day"``).
* ``temporal_blocked`` first half of the months vs second half, both directions
                       (for a Jan-Dec year: train Jan-Jun / test Jul-Dec and vice versa).
                       The Italian fire season (Jun-Sep) is mostly in H2, so this tests
                       transfer between fire regimes (quiet season <-> peak season),
                       i.e. whether the calibration is stable when fire activity changes.
* ``spatial_kfold``    K folds over cells (grouped by ``cell_id``, fixed seed).
* ``spatial_ns``       north vs south of the median cell latitude, both directions
                       (tests transfer between climatic/landcover regions).

Scores (on test rows, predicted VIIRS-equivalent vs observed VIIRS):
``bias_pct`` (100 * (sum pred - sum obs) / sum obs), ``r2_log`` (R^2 on log1p at
cell-period level), ``r2_raw``, ``r2_monthly`` (R^2 of national monthly totals),
``spearman_months`` (rank agreement of monthly totals), ``mae`` (cell-period).
``r2_log_pos`` (R^2 on log1p restricted to rows with MODIS > 0).
R^2 is the coefficient of determination 1 - SS_res/SS_tot (can be < 0), not r^2.

Two evaluation modes (column ``eval_mode``):
* ``backcast`` (primary): prediction forced to 0 where MODIS = 0. In a year without VIIRS
  the VIIRS-only cells do not exist, so any mass a model puts on x = 0 is not available.
* ``union``: the model is applied to every row of the paired table, x = 0 included.
The ``raw_modis`` baseline predicts VIIRS = MODIS (no calibration).
"""
from __future__ import annotations

import warnings
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import METRICS, DAYNIGHT, MODIS_ALL, Config

BASELINE = "raw_modis"
EVAL_SOURCES = (MODIS_ALL, "MODIS_AQUA")
SCHEMES = ("temporal_lomo", "temporal_blocked", "spatial_kfold", "spatial_ns")
N_SPATIAL_FOLDS = 5
SEED = 20250101


# ---------------------------------------------------------------- model backend
def _stub_fit(name: str, x, y) -> dict:
    """Local stand-in for B's fit_model (used only if harmonize.calibrate is missing)."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if name == "ratio":
        return {"model": "ratio", "k": float(y.sum() / max(x.sum(), 1e-12))}
    if name == "loglog":
        off = 1.0
        m = (x > 0) | (y > 0)
        lx, ly = np.log(x[m] + off), np.log(y[m] + off)
        b, a = np.polyfit(lx, ly, 1)
        resid = ly - (a + b * lx)
        return {"model": "loglog", "a": float(a), "b": float(b), "offset": off,
                "smearing": float(np.mean(np.exp(resid)))}
    raise ValueError(name)


def _stub_apply(params: dict, x) -> np.ndarray:
    x = np.asarray(x, float)
    if params["model"] == "ratio":
        return params["k"] * x
    p = params
    return np.maximum(0.0, p["smearing"] * np.exp(p["a"]) * (x + p["offset"]) ** p["b"] - p["offset"])


def get_backend():
    """Return (model_names, fit_fn, apply_fn, backend_label)."""
    try:
        from . import calibrate as cal  # noqa: WPS433
        names = list(cal.MODELS.keys()) if isinstance(cal.MODELS, dict) else list(cal.MODELS)
        return names, cal.fit_model, cal.apply_model, "harmonize.calibrate"
    except ImportError:
        warnings.warn("harmonize.calibrate not importable; validating the local stub models")
        return ["ratio", "loglog"], _stub_fit, _stub_apply, "stub"


# ---------------------------------------------------------------- folds
def month_key(period: pd.Series) -> pd.Series:
    return period.astype(str).str[:7]


def make_folds(df: pd.DataFrame, scheme: str, seed: int = SEED,
               n_spatial: int = N_SPATIAL_FOLDS) -> list[tuple[str, np.ndarray]]:
    """Return [(fold_name, test_mask)]; train = ~test_mask. Test masks partition the rows."""
    months = month_key(df["period"])
    if scheme == "temporal_lomo":
        return [(m, (months == m).to_numpy()) for m in sorted(months.unique())]
    if scheme == "temporal_blocked":
        um = sorted(months.unique())
        h1 = set(um[: len(um) // 2])
        in_h1 = months.isin(h1).to_numpy()
        return [(f"test_{um[len(um)//2]}..{um[-1]}", ~in_h1),
                (f"test_{um[0]}..{um[len(um)//2 - 1]}", in_h1)]
    if scheme == "spatial_kfold":
        cells = np.array(sorted(df["cell_id"].unique()))
        rng = np.random.default_rng(seed)
        fold_of = dict(zip(rng.permutation(cells), np.arange(len(cells)) % n_spatial))
        f = df["cell_id"].map(fold_of).to_numpy()
        return [(f"fold{k}", f == k) for k in range(n_spatial)]
    if scheme == "spatial_ns":
        lat_by_cell = df.groupby("cell_id")["cell_lat"].first()
        cut = float(lat_by_cell.median())
        north = (df["cell_lat"] > cut).to_numpy()
        return [(f"test_north_of_{cut:.3f}", north), (f"test_south_of_{cut:.3f}", ~north)]
    raise ValueError(f"unknown scheme {scheme!r}")


# ---------------------------------------------------------------- scores
def _r2(obs, pred) -> float:
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    sst = np.sum((obs - obs.mean()) ** 2)
    return float(1 - np.sum((obs - pred) ** 2) / sst) if sst > 0 else np.nan


def _spearman(a, b) -> float:
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return np.nan
    return float(spearmanr(a, b).statistic)


def score(obs: np.ndarray, pred: np.ndarray, months: np.ndarray, x=None) -> dict:
    """``x`` (MODIS input) enables ``r2_log_pos``: R^2 on log1p over rows with MODIS > 0,
    i.e. the cell-level skill where the model has something to work with."""
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    tot = obs.sum()
    mt = pd.DataFrame({"m": months, "o": obs, "p": pred}).groupby("m")[["o", "p"]].sum()
    return {
        "n_test": int(len(obs)),
        "bias_pct": float(100 * (pred.sum() - tot) / tot) if tot > 0 else np.nan,
        "r2_log": _r2(np.log1p(obs), np.log1p(pred)),
        "r2_log_pos": (_r2(np.log1p(obs[x > 0]), np.log1p(pred[x > 0]))
                       if x is not None and (np.asarray(x) > 0).sum() > 1 else np.nan),
        "r2_raw": _r2(obs, pred),
        "r2_monthly": _r2(mt["o"], mt["p"]) if len(mt) >= 2 else np.nan,
        "spearman_months": _spearman(mt["o"].to_numpy(), mt["p"].to_numpy()),
        "mae": float(np.mean(np.abs(pred - obs))),
    }


# ---------------------------------------------------------------- core loop
def _predict_oof(sub_by_dn: dict[str, pd.DataFrame], metric: str, model: str,
                 test_masks: dict[str, list], fit: Callable, apply: Callable,
                 min_pairs: int) -> dict[str, list[np.ndarray]]:
    """OOF predictions per daynight, per fold. D/N fits with < min_pairs training rows
    fall back to the ALL fit of the same fold (mirrors the schema §4 fallback)."""
    out: dict[str, list] = {}
    all_params: list = []
    for dn in ("ALL", "D", "N"):
        if dn not in sub_by_dn:
            continue
        d = sub_by_dn[dn]
        x = d[f"modis_{metric}"].to_numpy(float)
        y = d[f"viirs_{metric}"].to_numpy(float)
        preds = []
        for i, (_, test) in enumerate(test_masks[dn]):
            if model == BASELINE:
                preds.append(x[test].copy())
                continue
            train = ~test
            if dn == "ALL" or train.sum() >= min_pairs:
                params = fit(model, x[train], y[train]) if train.sum() >= 2 else None
            else:
                params = all_params[i] if i < len(all_params) else None
            if dn == "ALL":
                all_params.append(params)
            preds.append(np.full(test.sum(), np.nan) if params is None
                         else np.asarray(apply(params, x[test]), float))
        out[dn] = preds
    return out


def run_validation(paired_by_source: dict[str, pd.DataFrame], cfg: Config,
                   models=None) -> dict[str, pd.DataFrame]:
    """Evaluate every metric x model x modis_source x daynight under every scheme.

    Returns {"scores", "fold_scores", "monthly_oof", "summary"} and writes each to
    ``cfg.out_dir / "validation" / <name>.csv``.
    """
    names, fit, apply, backend = get_backend()
    model_list = [BASELINE] + [m for m in (models or names) if m != BASELINE]
    rows, frows, mrows = [], [], []
    for src in EVAL_SOURCES:
        if src not in paired_by_source:
            continue
        p = paired_by_source[src].reset_index(drop=True)
        sub_by_dn = {dn: p[p["daynight"] == dn].reset_index(drop=True) for dn in DAYNIGHT}
        sub_by_dn = {k: v for k, v in sub_by_dn.items() if len(v)}
        for scheme in SCHEMES:
            # folds are defined on the ALL table and re-derived per daynight table from
            # the same months / cell assignment / latitude cut (consistent across D/N/ALL)
            ref = sub_by_dn.get("ALL", p)
            masks = {}
            for dn, d in sub_by_dn.items():
                folds = make_folds(pd.concat([ref, d], ignore_index=True), scheme)
                masks[dn] = [(n, m[len(ref):]) for n, m in folds]
            for metric in METRICS:
                for model in model_list:
                    try:
                        oof = _predict_oof(sub_by_dn, metric, model, masks, fit, apply,
                                           cfg.min_pairs_for_split_fit)
                    except Exception as e:  # a model failing must not kill the run
                        warnings.warn(f"{model}/{metric}/{src}/{scheme} failed: {e}")
                        continue
                    for dn, preds in oof.items():
                        d = sub_by_dn[dn]
                        x_all = d[f"modis_{metric}"].to_numpy(float)
                        obs_all = d[f"viirs_{metric}"].to_numpy(float)
                        mon_all = month_key(d["period"]).to_numpy()
                        pred_union = np.full(len(d), np.nan)
                        for (_, test), pr in zip(masks[dn], preds):
                            pred_union[test] = pr
                        # "backcast": rows where MODIS saw nothing do not exist without
                        # VIIRS, so their prediction is 0 (VIIRS-only mass is lost).
                        pred_bc = np.where(x_all > 0, pred_union, 0.0)
                        for mode, pred_all in (("backcast", pred_bc), ("union", pred_union)):
                            tags = dict(scheme=scheme, eval_mode=mode, metric=metric, model=model,
                                        modis_source=src, daynight=dn)
                            fold_bias, fold_sp = [], []
                            for fname, test in masks[dn]:
                                t = test & ~np.isnan(pred_all)
                                if t.sum() == 0:
                                    continue
                                s = score(obs_all[t], pred_all[t], mon_all[t], x_all[t])
                                fold_bias.append(s["bias_pct"])
                                fold_sp.append(s["spearman_months"])
                                frows.append(dict(fold=fname, **tags, **s))
                            ok = ~np.isnan(pred_all)
                            s = score(obs_all[ok], pred_all[ok], mon_all[ok], x_all[ok])
                            s["n_nan_pred"] = int((~ok).sum())
                            fb = np.asarray(fold_bias, float)
                            s["bias_pct_fold_sd"] = float(np.nanstd(fb)) if np.isfinite(fb).any() else np.nan
                            s["bias_pct_fold_maxabs"] = (float(np.nanmax(np.abs(fb)))
                                                         if np.isfinite(fb).any() else np.nan)
                            fs = np.asarray(fold_sp, float)
                            s["spearman_fold_mean"] = float(np.nanmean(fs)) if np.isfinite(fs).any() else np.nan
                            rows.append(dict(**tags, backend=backend, **s))
                            mt = (pd.DataFrame({"period": mon_all[ok], "obs": obs_all[ok],
                                                "pred": pred_all[ok]})
                                  .groupby("period", as_index=False).sum())
                            for k, v in tags.items():
                                mt[k] = v
                            mrows.append(mt)
    scores = pd.DataFrame(rows)
    fold_scores = pd.DataFrame(frows)
    monthly = pd.concat(mrows, ignore_index=True) if mrows else pd.DataFrame()
    summary = summarize(scores)
    res = {"scores": scores, "fold_scores": fold_scores, "monthly_oof": monthly, "summary": summary}
    out = cfg.out_dir / "validation"
    out.mkdir(parents=True, exist_ok=True)
    for k, v in res.items():
        v.to_csv(out / f"{k}.csv", index=False)
    return res


def summarize(scores: pd.DataFrame) -> pd.DataFrame:
    """Worst case over the four schemes per (metric, model, source, daynight), then rank.

    rank_score = mean of the ranks of: worst |bias|, worst r2_log_pos, worst r2_monthly,
    worst spearman_months. ``rank_in_metric`` ranks models within a metric/source/daynight;
    ``rank_overall`` ranks metric+model combinations within a source/daynight (the
    "which metric to harmonize" question). Lower is better.
    """
    if scores.empty:
        return scores
    keys = ["eval_mode", "metric", "model", "modis_source", "daynight"]
    g = scores.assign(abs_bias=scores["bias_pct"].abs()).groupby(keys)
    s = pd.DataFrame({
        "worst_abs_bias_pct": g["abs_bias"].max(),
        "mean_abs_bias_pct": g["abs_bias"].mean(),
        "worst_fold_abs_bias_pct": g["bias_pct_fold_maxabs"].max(),
        "min_r2_log": g["r2_log"].min(),
        "mean_r2_log": g["r2_log"].mean(),
        "min_r2_log_pos": g["r2_log_pos"].min(),
        "min_r2_raw": g["r2_raw"].min(),
        "min_r2_monthly": g["r2_monthly"].min(),
        "min_spearman_months": g["spearman_months"].min(),
        "mean_mae": g["mae"].mean(),
    }).reset_index()

    def _rank_score(df: pd.DataFrame, grp: list[str]) -> pd.Series:
        g = df.groupby(grp)
        return (g["worst_abs_bias_pct"].rank() + g["min_r2_log_pos"].rank(ascending=False)
                + g["min_r2_monthly"].rank(ascending=False)
                + g["min_spearman_months"].rank(ascending=False)) / 4

    grp = ["eval_mode", "metric", "modis_source", "daynight"]
    s["rank_score"] = _rank_score(s, grp)
    s["rank_in_metric"] = s.groupby(grp)["rank_score"].rank(method="min")
    cal = s[s["model"] != BASELINE].copy()
    cal["rs"] = _rank_score(cal, ["eval_mode", "modis_source", "daynight"])
    s["rank_overall"] = cal.groupby(["eval_mode", "modis_source", "daynight"])["rs"].rank(method="min")
    return s.sort_values(["eval_mode", "modis_source", "daynight", "metric", "rank_in_metric"]
                         ).reset_index(drop=True)


if __name__ == "__main__":  # quick manual run on a paired CSV: python -m harmonize.validate file.csv
    import sys
    df = pd.read_csv(sys.argv[1], dtype={"cell_id": str, "period": str})
    cfg = Config(out_dir=sys.argv[2] if len(sys.argv) > 2 else "outputs")
    res = run_validation({s: d for s, d in df.groupby("modis_source")}, cfg)
    pd.set_option("display.width", 200)
    print(res["summary"].query("daynight == 'ALL' and eval_mode == 'backcast'").round(3).to_string())
