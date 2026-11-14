"""MODIS -> VIIRS-equivalent calibration (owner: B).

Public API (see SCHEMA.md §0, §4):

* ``MODELS`` - names accepted by :func:`fit_model`.
* ``fit_model(name, x, y, **opts) -> params`` - params are self-describing
  (``params["model"]``) and JSON-serialisable; they can be applied to another year
  without refitting.
* ``apply_model(params, x) -> ndarray``.
* ``stability_table(paired_by_source, cfg) -> DataFrame`` - month-to-month stability
  and leave-one-month-out (LOMO) national-total errors for every candidate.
* ``fit_all(paired_by_source, cfg, training_meta=None, stability=None) -> dict`` - §4 JSON.
* ``apply_coefficients(coef_json, metric, modis_source, daynight, x, model=None,
  fit_level=None, cfg=None) -> ndarray``.

Key modelling point - the "VIIRS-only" cells
--------------------------------------------
The paired table is the *union* of cells seen by either sensor, so ~60 % of rows have
MODIS = 0 and VIIRS > 0.  In a back-cast year (no VIIRS) those rows do not exist: we only
ever get to apply the model to cells where MODIS saw something.  Any VIIRS mass that a
model attributes to ``x = 0`` is therefore *lost* in a back-cast.  The LOMO check below
reproduces that situation (``lomo_*`` metrics predict only rows with MODIS > 0 and compare
against the full VIIRS national total).  ``ratio`` and ``powerlaw_total`` fold the
VIIRS-only mass into the MODIS>0 cells by construction; ``loglog`` and ``poisson``
put part of it on ``x = 0`` (their intercept), which is honest at cell level but biases
back-cast totals low.

Models
------
ratio           y = k x,                       k = sum(y) / sum(x)
loglog          log(y+o) = a + b log(x+o) + e;  y = max(0, s e^a (x+o)^b - o),  s = Duan smearing
poisson         E[y] = e^a (x+o)^b,              Poisson pseudo-likelihood (exact in-sample totals)
powerlaw_total  E[y] = c x^b for x > 0, 0 at x = 0; b by Poisson pseudo-likelihood on x>0 rows,
                c rescaled so that sum_{x>0} c x^b = sum(y) over *all* rows
"""
from __future__ import annotations

import math
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import optimize

from .config import DAYNIGHT, METRICS, MODIS_ALL, Config

MODELS = ["ratio", "loglog", "poisson", "powerlaw_total"]
FIT_LEVELS = ("cell_period", "national_period")
DN_SPLIT = "DN_SPLIT"   # pseudo-daynight in the stability table: D and N fitted separately, summed
DEFAULT_OFFSET = 1.0
MIN_ROWS_POWER = 3      # minimum usable rows (x>0 for powerlaw) to estimate a slope
# sources eligible for the recommendation (Terra is reported for information only)
RECOMMEND_SOURCES = (MODIS_ALL, "MODIS_AQUA")


# --------------------------------------------------------------------------- helpers
def _f(v) -> float | None:
    """JSON-safe float (NaN/inf -> None)."""
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _p(params: dict, key: str, default=np.nan) -> float:
    v = params.get(key, default)
    return np.nan if v is None else float(v)


def _clean(x, y):
    """Float arrays, drop pairs with NaN/inf or negative values."""
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if x.shape != y.shape:
        raise ValueError(f"x and y must have the same length ({x.size} vs {y.size})")
    ok = np.isfinite(x) & np.isfinite(y) & (x >= 0) & (y >= 0)
    return x[ok], y[ok]


def _poisson_loglinear(z, y, b_init=1.0):
    """Fit E[y] = exp(a + b z) by Poisson pseudo-likelihood. Returns (a, b)."""
    sy = y.sum()
    if sy <= 0:
        return -np.inf, b_init
    if np.ptp(z) == 0:                       # no slope information: intercept only, b fixed
        return math.log(sy / (np.exp(b_init * z).sum())), b_init
    zc = z.mean()

    def nll(t):
        eta = np.clip(t[0] + t[1] * (z - zc), -50, 50)
        mu = np.exp(eta)
        r = mu - y
        return (mu - y * eta).sum(), np.array([r.sum(), (r * (z - zc)).sum()])

    a0 = math.log(sy / np.exp(b_init * (z - zc)).sum())
    res = optimize.minimize(nll, np.array([a0, b_init]), jac=True, method="BFGS")
    a_c, b = res.x
    return float(a_c - b * zc), float(b)


# --------------------------------------------------------------------------- fit / apply
def fit_model(name: str, x, y, offset: float = DEFAULT_OFFSET) -> dict:
    """Fit model ``name`` to MODIS ``x`` -> VIIRS ``y`` (array-likes, same length).

    Rows with NaN or negative values are dropped. Degenerate input (empty, all-zero x)
    never raises: it returns params with NaN (``None``) coefficients and
    ``"degenerate": True`` so that :func:`apply_model` yields NaN, plus a warning.
    """
    if name not in MODELS:
        raise ValueError(f"unknown model {name!r}; choose from {MODELS}")
    x, y = _clean(x, y)
    n = int(x.size)
    params: dict = {"model": name, "n_fit": n}
    pos = x > 0

    if name == "ratio":
        sx = x.sum()
        k = y.sum() / sx if sx > 0 else np.nan
        params["k"] = _f(k)

    elif name == "loglog":
        o = float(offset)
        params["offset"] = o
        if n == 0:
            a = b = s = np.nan
        else:
            lx, ly = np.log(x + o), np.log(y + o)
            if n >= 2 and np.ptp(lx) > 0:
                b, a = np.polyfit(lx, ly, 1)
            else:                             # no slope information: b = 1
                b = 1.0
                a = float(np.mean(ly - lx))
            resid = ly - (a + b * lx)
            s = float(np.mean(np.exp(resid)))  # Duan (1983) smearing estimator
        params.update(a=_f(a), b=_f(b), smearing=_f(s))

    elif name == "poisson":
        o = float(offset)
        params["offset"] = o
        if n == 0:
            a = b = np.nan
        else:
            a, b = _poisson_loglinear(np.log(x + o), y)
        params.update(a=_f(a), b=_f(b))
        if n > 0 and y.sum() == 0:            # all y == 0 -> predict 0 everywhere
            params["zero"] = True

    elif name == "powerlaw_total":
        if pos.sum() == 0:
            c = b = np.nan
        else:
            xp, yp = x[pos], y[pos]
            if pos.sum() >= MIN_ROWS_POWER and yp.sum() > 0:
                _, b = _poisson_loglinear(np.log(xp), yp)
            else:
                b = 1.0
            denom = np.power(xp, b).sum()
            c = y.sum() / denom if denom > 0 else np.nan
        params.update(c=_f(c), b=_f(b))

    params["degenerate"] = not all(
        params.get(k) is not None for k in ("k", "a", "b", "c", "smearing") if k in params
    ) and not params.get("zero", False)
    if params["degenerate"]:
        warnings.warn(f"fit_model({name}): degenerate input (n={n}, n_x>0={int(pos.sum())}); "
                      "coefficients are NaN", RuntimeWarning, stacklevel=2)
    return params


def apply_model(params: dict, x) -> np.ndarray:
    """Apply fitted ``params`` to MODIS values ``x``. Output >= 0 (NaN where x is NaN or the
    fit was degenerate). Negative x is treated as 0."""
    x = np.atleast_1d(np.asarray(x, dtype=float))
    nan = ~np.isfinite(x)
    x = np.where(nan, 0.0, np.clip(x, 0.0, None))
    m = params.get("model")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        if m == "ratio":
            out = _p(params, "k") * x
        elif m == "loglog":
            o, a, b, s = (_p(params, k) for k in ("offset", "a", "b", "smearing"))
            out = np.maximum(0.0, s * np.exp(a) * np.power(x + o, b) - o)
        elif m == "poisson":
            if params.get("zero"):
                out = np.zeros_like(x)
            else:
                o, a, b = (_p(params, k) for k in ("offset", "a", "b"))
                out = np.exp(a) * np.power(x + o, b)
        elif m == "powerlaw_total":
            c, b = _p(params, "c"), _p(params, "b")
            out = np.where(x > 0, c * np.power(np.where(x > 0, x, 1.0), b), 0.0)
        else:
            raise ValueError(f"unknown model in params: {m!r}")
    out = np.asarray(out, dtype=float)
    out[nan] = np.nan
    return out


# --------------------------------------------------------------------------- data helpers
def _xy(df: pd.DataFrame, metric: str):
    return df[f"modis_{metric}"].to_numpy(float), df[f"viirs_{metric}"].to_numpy(float)


def _national(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    return (df.groupby("period")[[f"modis_{metric}", f"viirs_{metric}"]].sum().reset_index())


def _level_frame(df: pd.DataFrame, metric: str, level: str) -> pd.DataFrame:
    return df if level == "cell_period" else _national(df, metric)


def _n_pairs(df: pd.DataFrame, metric: str) -> int:
    """Number of informative pairs = rows where MODIS saw something."""
    return int((df[f"modis_{metric}"] > 0).sum())


def _fit_stats(params, x, y) -> dict:
    x, y = _clean(x, y)
    pred = apply_model(params, x)
    sy = y.sum()
    ok = np.isfinite(pred)
    r2 = np.nan
    if ok.sum() >= 2:
        ly, lp = np.log1p(y[ok]), np.log1p(pred[ok])
        sst = ((ly - ly.mean()) ** 2).sum()
        r2 = 1 - ((ly - lp) ** 2).sum() / sst if sst > 0 else np.nan
    bias = (np.nansum(pred) - sy) / sy * 100 if sy > 0 and ok.any() else np.nan
    bias_bc = (np.nansum(pred[x > 0]) - sy) / sy * 100 if sy > 0 and ok.any() else np.nan
    return {"r2_log": _f(r2), "bias_pct": _f(bias), "bias_pct_backcast": _f(bias_bc)}


def _wcv(v, w) -> float:
    """Weighted coefficient of variation (weights = data volume, so near-empty months with
    erratic ratios do not dominate)."""
    v = np.asarray([np.nan if t is None else t for t in v], dtype=float)
    w = np.asarray(w, dtype=float)
    ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
    if ok.sum() < 2:
        return np.nan
    v, w = v[ok], w[ok]
    m = np.average(v, weights=w)
    if m == 0:
        return np.nan
    return float(np.sqrt(np.average((v - m) ** 2, weights=w)) / abs(m))


def _subset(df: pd.DataFrame, dn: str) -> pd.DataFrame:
    return df[df["daynight"] == dn]


def _fit_dn(df: pd.DataFrame, metric, model, dn, level, cfg) -> tuple[dict, str]:
    """Fit on daynight ``dn``; falls back to ALL if too few pairs. Returns (params, used_dn)."""
    sub = _subset(df, dn)
    used = dn
    if dn != "ALL" and _n_pairs(sub, metric) < cfg.min_pairs_for_split_fit:
        sub, used = _subset(df, "ALL"), "ALL"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return fit_model(model, *_xy(_level_frame(sub, metric, level), metric)), used


# --------------------------------------------------------------------------- stability
def _predict_backcast_total(params, df, metric, level) -> float:
    """Back-cast-realistic national total: only rows with MODIS > 0 exist without VIIRS."""
    x = df[f"modis_{metric}"].to_numpy(float)
    if level == "national_period":
        return float(apply_model(params, [x.sum()])[0])
    return float(np.nansum(apply_model(params, x[x > 0]))) if (x > 0).any() else 0.0


def _predict_union_total(params, df, metric, level) -> float:
    x = df[f"modis_{metric}"].to_numpy(float)
    if level == "national_period":
        return float(apply_model(params, [x.sum()])[0])
    return float(np.nansum(apply_model(params, x)))


def _candidate_rows(df, metric, model, src, level, cfg):
    periods = sorted(df["period"].unique())
    dns = ["D", "N", "ALL", DN_SPLIT]
    rows = []
    for dn in dns:
        parts = ["D", "N"] if dn == DN_SPLIT else [dn]
        # truth per month
        truth = {p: sum(_subset(df[df.period == p], q)[f"viirs_{metric}"].sum() for q in parts)
                 for p in periods}
        # full fit (in-sample) and coefficient summary
        full = {q: _fit_dn(df, metric, model, q, level, cfg) for q in parts}
        # LOMO
        pred_bc, pred_un = {}, {}
        for p in periods:
            tr, te = df[df.period != p], df[df.period == p]
            tot_bc = tot_un = 0.0
            for q in parts:
                prm, _ = _fit_dn(tr, metric, model, q, level, cfg)
                tot_bc += _predict_backcast_total(prm, _subset(te, q), metric, level)
                tot_un += _predict_union_total(prm, _subset(te, q), metric, level)
            pred_bc[p], pred_un[p] = tot_bc, tot_un
        t = np.array([truth[p] for p in periods], float)
        pb = np.array([pred_bc[p] for p in periods], float)
        pu = np.array([pred_un[p] for p in periods], float)
        okb = np.isfinite(pb)
        st = t[okb].sum()
        wape = np.abs(pb - t)[okb].sum() / st * 100 if st > 0 else np.nan
        wape_u = np.abs(pu - t)[okb].sum() / st * 100 if st > 0 else np.nan
        bias = (pb[okb].sum() - st) / st * 100 if st > 0 else np.nan
        m = okb & (t > 0)
        mape = np.mean(np.abs(pb[m] - t[m]) / t[m]) * 100 if m.any() else np.nan
        m2 = m & (pb > 0)
        rmse_log = float(np.sqrt(np.mean(np.log(pb[m2] / t[m2]) ** 2))) if m2.any() else np.nan
        # month-to-month stability: per-month fit at cell level (k of ratio, b of power models)
        ks, kw, bs, bw = [], [], [], []
        for p in periods:
            mon = df[df.period == p]
            sx = sum(_subset(mon, q)[f"modis_{metric}"].sum() for q in parts)
            sy = sum(_subset(mon, q)[f"viirs_{metric}"].sum() for q in parts)
            ks.append(sy / sx if sx > 0 else np.nan)
            kw.append(sx)
            if model != "ratio" and level == "cell_period" and dn != DN_SPLIT:
                sub = _subset(mon, dn)
                npm = _n_pairs(sub, metric)
                if npm >= MIN_ROWS_POWER:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        bs.append(fit_model(model, *_xy(sub, metric)).get("b"))
                    bw.append(npm)
        p0 = full[parts[0]][0]
        rows.append({
            "metric": metric, "model": model, "modis_source": src, "daynight": dn,
            "fit_level": level,
            "fallback_to_all": any(u != q for q, (_, u) in full.items()),
            "n_pairs": sum(_n_pairs(_subset(df, q), metric) for q in parts),
            "coef_k": p0.get("k", p0.get("c")) if dn != DN_SPLIT else None,
            "coef_b": p0.get("b") if dn != DN_SPLIT else None,
            "cv_k_monthly": _wcv(ks, kw),
            "cv_b_monthly": _wcv(bs, bw) if bs else np.nan,
            "lomo_wape_pct": wape, "lomo_mape_pct": mape, "lomo_bias_pct": bias,
            "lomo_rmse_log": rmse_log, "lomo_wape_union_pct": wape_u,
            "n_months": len(periods),
        })
    return rows


def stability_table(paired_by_source: dict[str, pd.DataFrame], cfg: Config) -> pd.DataFrame:
    """Compare every (metric, model, modis_source, daynight, fit_level) candidate.

    Columns
    -------
    cv_k_monthly        CV across months of the monthly ratio of national totals (VIIRS/MODIS),
                        weighted by monthly MODIS total
    cv_b_monthly        CV across months of the exponent b fitted per month (cell level),
                        weighted by the month's number of MODIS>0 pairs
    lomo_wape_pct       leave-one-month-out: fit on 11 months, predict the held-out month's
                        national total from MODIS>0 rows only (back-cast-realistic);
                        sum|err| / sum(truth) * 100. Primary selection criterion.
    lomo_mape_pct       same, unweighted mean of monthly |err|/truth (dominated by tiny months)
    lomo_bias_pct       same, (sum pred - sum truth) / sum truth
    lomo_rmse_log       RMS of log(pred/truth) across months (scale-free)
    lomo_wape_union_pct as lomo_wape but also predicting MODIS=0 rows (needs VIIRS; info only)
    daynight=DN_SPLIT   D and N fitted separately (with fallback) and summed, vs VIIRS D+N.
    """
    rows = []
    for src, df in paired_by_source.items():
        if df is None or len(df) == 0:
            continue
        for metric in METRICS:
            for model in MODELS:
                for level in FIT_LEVELS:
                    rows.extend(_candidate_rows(df, metric, model, src, level, cfg))
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["lomo_wape_pct", "cv_k_monthly"], na_position="last",
                              ignore_index=True)
    return out


MODEL_SIMPLICITY = {"ratio": 0, "powerlaw_total": 1, "poisson": 2, "loglog": 3}
WAPE_TOLERANCE_PP = 1.0   # candidates within this many points of the best are "tied"


def _recommend(stab: pd.DataFrame) -> dict:
    """Selection rule.

    1. Eligible: MODIS_ALL / MODIS_AQUA, daynight ALL or DN_SPLIT, fit_level cell_period
       (harmonized.csv is cell-level; national fits are reported as a check only).
    2. Primary score: back-cast LOMO WAPE of national monthly totals.
    3. With 12 months, differences of ~1 point are noise: among candidates within
       WAPE_TOLERANCE_PP of the best, prefer the simplest model, then ALL over DN_SPLIT,
       then MODIS_ALL (longest record), then lower WAPE.
    """
    cand = stab[stab.modis_source.isin(RECOMMEND_SOURCES)
                & stab.daynight.isin(["ALL", DN_SPLIT])
                & (stab.fit_level == "cell_period")
                & stab.lomo_wape_pct.notna()].copy()
    if cand.empty:
        return {"metric": "n_hotspots", "model": "ratio", "modis_source": MODIS_ALL,
                "fit_level": "cell_period", "use_daynight_split": False,
                "reason": "no stability information available; default"}
    best_wape = cand.lomo_wape_pct.min()
    tied = cand[cand.lomo_wape_pct <= best_wape + WAPE_TOLERANCE_PP].copy()
    tied["_m"] = tied.model.map(MODEL_SIMPLICITY).fillna(9)
    tied["_d"] = (tied.daynight == DN_SPLIT).astype(int)
    tied["_s"] = (tied.modis_source != MODIS_ALL).astype(int)
    best = tied.sort_values(["_m", "_d", "_s", "lomo_wape_pct"]).iloc[0]
    overall = cand.sort_values("lomo_wape_pct").iloc[0]
    loglog = cand[(cand.metric == best.metric) & (cand.model == "loglog")
                  & (cand.modis_source == best.modis_source) & (cand.daynight == "ALL")]
    ll_txt = (f" loglog (same metric/source) is biased {loglog.lomo_bias_pct.iloc[0]:+.0f}% in the "
              f"back-cast (union WAPE {loglog.lomo_wape_union_pct.iloc[0]:.0f}%): the log-space "
              f"slope under-predicts the large cells that dominate totals and part of its mass "
              f"sits on MODIS=0 cells, which do not exist without VIIRS." if len(loglog) else "")
    reason = (f"Back-cast leave-one-month-out national-total error (only MODIS>0 cells "
              f"predicted): WAPE {best.lomo_wape_pct:.1f}%, bias {best.lomo_bias_pct:+.1f}%, "
              f"volume-weighted CV of the monthly VIIRS/MODIS ratio {best.cv_k_monthly:.2f}. "
              f"Best overall cell-level candidate was {overall.metric}/{overall.model}/"
              f"{overall.modis_source}/{overall.daynight} at {overall.lomo_wape_pct:.1f}%; "
              f"{len(tied)} candidates within {WAPE_TOLERANCE_PP:g} pt were treated as tied and "
              f"the simplest was chosen.{ll_txt}")
    return {"metric": best.metric, "model": best.model, "modis_source": best.modis_source,
            "fit_level": best.fit_level, "use_daynight_split": bool(best.daynight == DN_SPLIT),
            "lomo_wape_pct": _f(best.lomo_wape_pct), "lomo_bias_pct": _f(best.lomo_bias_pct),
            "cv_k_monthly": _f(best.cv_k_monthly), "reason": reason}


# --------------------------------------------------------------------------- fit_all / apply
def fit_all(paired_by_source: dict[str, pd.DataFrame], cfg: Config, training_meta=None,
            stability: pd.DataFrame | None = None) -> dict:
    """Fit every metric x model x source x daynight x fit_level and build the §4 JSON.

    D/N entries with fewer than ``cfg.min_pairs_for_split_fit`` pairs (rows with MODIS>0)
    are omitted, so :func:`apply_coefficients` falls back to ALL. ``stability`` may be a
    precomputed :func:`stability_table` (otherwise it is computed here).
    """
    meta = dict(training_meta or {})
    all_df = [d for d in paired_by_source.values() if d is not None and len(d)]
    if all_df:
        cat = pd.concat(all_df)
        meta.setdefault("periods", sorted(cat["period"].astype(str).unique().tolist()))
        meta.setdefault("n_cells", int(cat["cell_id"].nunique()))
    meta.setdefault("source_files", [])
    meta.setdefault("periods", [])
    meta.setdefault("n_cells", 0)

    coefs = []
    for src, df in paired_by_source.items():
        if df is None or len(df) == 0:
            continue
        for metric in METRICS:
            for dn in DAYNIGHT:
                sub = _subset(df, dn)
                npairs = _n_pairs(sub, metric)
                if dn != "ALL" and npairs < cfg.min_pairs_for_split_fit:
                    continue
                for level in FIT_LEVELS:
                    fr = _level_frame(sub, metric, level)
                    x, y = _xy(fr, metric)
                    for model in MODELS:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore", RuntimeWarning)
                            prm = fit_model(model, x, y)
                        coefs.append({
                            "metric": metric, "model": model, "modis_source": src,
                            "daynight": dn, "fit_level": level, "params": prm,
                            "n_train": int(len(fr)), "n_pairs": npairs,
                            "fit_stats": _fit_stats(prm, x, y),
                        })
    if stability is None:
        stability = stability_table(paired_by_source, cfg)
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": cfg.to_dict(),
        "training_data": meta,
        "recommended": _recommend(stability),
        "coefficients": coefs,
    }


def _find(coefs, **key):
    for c in coefs:
        if all(c.get(k) == v for k, v in key.items()):
            return c
    return None


def apply_coefficients(coef_json: dict, metric: str, modis_source: str, daynight: str, x,
                       model: str | None = None, fit_level: str | None = None,
                       cfg: Config | None = None) -> np.ndarray:
    """Convert MODIS values ``x`` to VIIRS-equivalent using the stored coefficients.

    ``model``/``fit_level`` default to the recommended ones. A missing D/N entry falls back
    to ``daynight="ALL"`` (with a warning). If ``cfg`` is given and its ``cell_size_deg`` /
    ``time_step`` differ from those used for training, a warning is issued.
    ``national_period`` coefficients are meant for national period totals, not cells.
    """
    rec = coef_json.get("recommended", {})
    model = model or rec.get("model", "ratio")
    fit_level = fit_level or rec.get("fit_level", "cell_period")
    trained = coef_json.get("config", {})
    if cfg is not None:
        for k in ("cell_size_deg", "time_step"):
            if k in trained and trained[k] != getattr(cfg, k):
                warnings.warn(f"coefficients were fitted with {k}={trained[k]!r} but current "
                              f"config has {getattr(cfg, k)!r}; results are not valid",
                              UserWarning, stacklevel=2)
    coefs = coef_json.get("coefficients", [])
    key = dict(metric=metric, model=model, modis_source=modis_source, fit_level=fit_level)
    entry = _find(coefs, daynight=daynight, **key)
    if entry is None and daynight != "ALL":
        entry = _find(coefs, daynight="ALL", **key)
        if entry is not None:
            warnings.warn(f"no {daynight} coefficients for {key}; using ALL",
                          UserWarning, stacklevel=2)
    if entry is None:
        raise KeyError(f"no coefficients for {key} daynight={daynight}")
    return apply_model(entry["params"], x)
