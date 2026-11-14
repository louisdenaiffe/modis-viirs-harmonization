"""MODIS -> VIIRS-equivalent calibration, global version (owner: B; SCHEMA.md §5).

Public API
----------
* ``MODELS`` - model names accepted by :func:`fit_model`.
* ``fit_model(name, paired, metric, cfg=None, **opts) -> params`` - fit on a §4 paired table
  (``modis_<m>``, ``viirs_<m>``, ``cell_lat``, ``cell_lon``, ``period``, ``daynight``, MODIS
  features). If the table holds several ``daynight`` values, one sub-model is fitted per value.
  ``params`` is JSON-serialisable and fully defines the predictions.
* ``apply_model(params, modis_rows, metric) -> ndarray`` - §3-shaped MODIS rows (``<metric>``,
  ``cell_lat``, ``cell_lon``, ``period``, ``daynight``, ``frp_mean``, ...). Never reads VIIRS
  columns. Output is >= 0, length ``len(modis_rows)``; rows with NaN / <= 0 MODIS give 0.
  Missing features fall back to their training mean; unseen regions to the parent tile / global.
* ``fit_all(paired_by_source, cfg, training_meta=None, stability=None) -> dict`` - the §5 JSON,
  with ``recommended`` chosen by leave-one-domain-out (90th percentile of |annual bias|).
* ``apply_coefficients(coef, metric, modis_rows, cfg=None, model=None) -> ndarray`` - dispatch
  on ``modis_rows["source"]`` (MODIS configuration) and ``daynight``, with fallbacks.
* ``stability_table(paired_by_source, cfg, ...) -> DataFrame`` - leave-one-domain-out
  predictions per held-out domain-year (and ``summarize_stability`` for the per-model summary).

Models (all multiplicative: prediction_row = k_row * MODIS_row, k clipped to ``k_clip``)
------------------------------------------------------------------------------------------
ratio_global    k = sum(VIIRS) / sum(MODIS).
ratio_regional  k of the nested tiles ``cfg.region_levels_deg`` (coarse -> fine). Each tile's
                k is shrunk toward its parent:  k_t = (V_t + lam * k_parent) / (M_t + lam),
                a Gamma-Poisson posterior mean with prior weight ``lam`` (in MODIS units).
                ``lam`` is chosen per level by an internal 2-fold spatial-block CV (1 deg
                checkerboard inside each tile). Unseen tile -> parent -> ... -> global.
glm_features    log k_row = b0 + beta . z_row, z from MODIS only. Default z (DEFAULT_FEATURES):
                log density of the metric in the cell (log M; log fraction of days for
                fire_cell_days), log hotspots per fire-day (fire size / saturation), log
                frp_mean, scan_mean (view angle), Terra share. |lat|, hemisphere-aware season
                and others are available via ``features=`` (they hurt leave-one-domain-out).
                Fitted by Poisson pseudo-likelihood on aggregated units (``unit_deg`` tile x
                period): E[V_unit] = sum_{rows in unit} M_row * exp(b0 + beta . z_row). The unit
                total includes VIIRS seen in cells where MODIS saw nothing, so that mass is
                folded into MODIS-positive rows and totals are preserved (the intercept's
                score equation gives sum predicted = sum observed in training). Features are
                clipped to the training 0.1-99.9 % range; missing ones take the training mean.
glm_regional    glm_features x a shrunken regional residual (same EB scheme as ratio_regional,
                with the GLM prediction as exposure).

``fire_cell_days`` predictions are capped at the number of days in the period.
"""
from __future__ import annotations

import math
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import DAYNIGHT, METRICS, MODIS_ALL, MODIS_CONFIGS, Config

MODELS = ("ratio_global", "ratio_regional", "glm_features", "glm_regional")
MODEL_SIMPLICITY = {m: i for i, m in enumerate(MODELS)}
K_CLIP = (0.05, 100.0)          # sane range for any multiplicative factor
FEATURES = ("ldens", "lhpd", "lfrp", "scan", "terra", "alat", "season_sin", "season_cos",
            "lnh", "lfcd", "lfrp_p90", "bright", "alat2")
# Default: sensor-physics features only. Adding |lat| / season made leave-one-domain-out
# transfer worse on the 12-country dev sample (p90 |bias| fire_cell_days 0.23 -> 0.19 without).
DEFAULT_FEATURES = ("ldens", "lhpd", "lfrp", "scan", "terra")
GLM_UNIT_DEG = 5.0              # aggregated fitting unit for the GLMs (tile x period)
CV_BLOCK = 0.5                  # internal CV blocks = tile size * this (checkerboard of half-tiles)
SUPPORT_FRAC = 0.25             # a tile's k applies only where its (deg * this) sub-block had data
LAM_GRID_DECADES = np.linspace(-3, 2, 11)   # lam = median tile exposure * 10**g (plus lam=0)
RESID_CLIP = (0.1, 10.0)        # regional residual range for glm_regional
RIDGE = 1e-6                    # relative ridge for the GLM (collinearity guard only)
SELECTION_TOL = 0.01            # p90 |bias| within 1 point of the best counts as tied
SELECTION_SOURCES = (MODIS_ALL,)
SELECTION_DAYNIGHT = ("ALL",)


# =========================================================================== small helpers
def _f(v):
    """JSON-safe float (NaN/inf -> None)."""
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _num(df: pd.DataFrame, col: str, n: int) -> np.ndarray:
    if df is not None and col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").to_numpy("float64", na_value=np.nan)
    return np.full(n, np.nan)


def _str(df: pd.DataFrame, col: str, n: int, default="ALL") -> np.ndarray:
    if col in df.columns:
        return df[col].astype("object").where(df[col].notna(), default).astype(str).to_numpy()
    return np.full(n, default, dtype=object)


def _tile_key(lat, lon, deg) -> np.ndarray:
    """Integer tile key (iy * 100000 + ix); -1 where lat/lon is missing."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    ok = np.isfinite(lat) & np.isfinite(lon)
    iy = np.floor((np.where(ok, lat, 0) + 90.0) / deg).astype("int64")
    ix = np.floor((np.where(ok, lon, 0) + 180.0) / deg).astype("int64")
    return np.where(ok, iy * 100000 + ix, -1)


def _key_str(k: int) -> str:
    return f"{k // 100000}_{k % 100000}"


def _key_int(s: str) -> int:
    a, b = s.split("_")
    return int(a) * 100000 + int(b)


def _period_info(period: np.ndarray):
    """period labels -> (factorized codes, month 1-12, days in period). Vectorised on uniques."""
    codes, uniq = pd.factorize(pd.Series(period, dtype="object").fillna(""))
    u = pd.Series(np.asarray(uniq, dtype=object)).astype(str)
    month = pd.to_numeric(u.str[5:7], errors="coerce").to_numpy(float)
    start = pd.to_datetime(u.str[:10] if len(u) else u, errors="coerce", format="mixed")
    is_day = u.str.len().to_numpy() >= 10
    dim = np.where(is_day, 1.0, start.dt.days_in_month.to_numpy(float) if len(u) else np.zeros(0))
    codes = np.asarray(codes, "int64")
    ok = codes >= 0
    m = np.full(len(codes), np.nan)
    d = np.full(len(codes), np.nan)
    m[ok] = month[codes[ok]]
    d[ok] = dim[codes[ok]]
    return codes, m, d


def _clip_k(k, kc):
    return np.clip(k, kc[0], kc[1])


# =========================================================================== row preparation
def _rows(df: pd.DataFrame, metric: str, prefix: str, with_y: bool) -> dict:
    """Compact numpy view of MODIS-side rows (prefix '' for §3 rows, 'modis_' for §4 paired)."""
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}; choose from {METRICS}")
    n = len(df)
    x = _num(df, prefix + metric, n)
    x = np.where(np.isfinite(x) & (x > 0), x, 0.0)
    lat, lon = _num(df, "cell_lat", n), _num(df, "cell_lon", n)
    per = df["period"].to_numpy(object) if "period" in df.columns else np.full(n, "", object)
    pcode, month, days = _period_info(per)
    nh = _num(df, prefix + "n_hotspots", n)
    fcd = _num(df, prefix + "fire_cell_days", n)
    frp_mean = _num(df, prefix + "frp_mean", n)
    frp_sum = _num(df, prefix + "frp_sum", n)
    frp_mean = np.where(np.isfinite(frp_mean), frp_mean, frp_sum / np.where(nh > 0, nh, np.nan))
    nt, na = _num(df, prefix + "n_terra", n), _num(df, prefix + "n_aqua", n)
    with np.errstate(divide="ignore", invalid="ignore"):
        dens = x / days if metric == "fire_cell_days" else x
        z = np.column_stack([
            np.log(np.where(x > 0, dens, np.nan)),
            np.log(np.where((nh > 0) & (fcd > 0), nh / fcd, np.nan)),
            np.log(np.where(frp_mean > 0, frp_mean, np.nan)),
            np.where(np.isfinite(_num(df, prefix + "scan_mean", n)), _num(df, prefix + "scan_mean", n), np.nan),
            nt / (nt + na),
            np.abs(lat) / 90.0,
            np.sin(2 * np.pi * (month - 1 + 6 * (lat < 0)) / 12),
            np.cos(2 * np.pi * (month - 1 + 6 * (lat < 0)) / 12),
            np.log(np.where(nh > 0, nh, np.nan)),
            np.log(np.where(fcd > 0, fcd / days, np.nan)),
            np.log(np.where(_num(df, prefix + "frp_p90", n) > 0, _num(df, prefix + "frp_p90", n), np.nan)),
            _num(df, prefix + "bright_mir_mean", n),
            (np.abs(lat) / 90.0) ** 2,
        ])
    z[~np.isfinite(z)] = np.nan
    out = {"x": x, "lat": lat, "lon": lon, "pcode": pcode, "days": days, "z": z,
           "dn": _str(df, "daynight", n)}
    if with_y:
        y = _num(df, "viirs_" + metric, n)
        out["y"] = np.where(np.isfinite(y) & (y > 0), y, 0.0)
    return out


def _subset(P: dict, mask) -> dict:
    return {k: v[mask] for k, v in P.items()}


# =========================================================================== nested regional EB
def _agg(keys, *vals):
    """Group-sum ``vals`` by integer ``keys`` -> (unique keys, inverse, sums...)."""
    u, inv = np.unique(keys, return_inverse=True)
    return (u, inv) + tuple(np.bincount(inv, weights=v, minlength=len(u)) for v in vals)


def _lookup(table_keys: np.ndarray, table_vals: np.ndarray, keys: np.ndarray):
    """Vectorised dict lookup; NaN where missing."""
    out = np.full(len(keys), np.nan)
    if len(table_keys) == 0 or len(keys) == 0:
        return out
    order = np.argsort(table_keys)
    tk, tv = table_keys[order], table_vals[order]
    pos = np.clip(np.searchsorted(tk, keys), 0, len(tk) - 1)
    hit = tk[pos] == keys
    out[hit] = tv[pos[hit]]
    return out


def _shrunk(Y, E, kp, lam):
    with np.errstate(divide="ignore", invalid="ignore"):
        k = (Y + lam * kp) / (E + lam)
    return np.where(E + lam > 0, k, kp)


def _choose_lam(tk, blk, E, Y, kp_row, kc):
    """Pick the prior weight lam by 2-fold spatial-block CV inside each tile: the k shrunk on
    one half of a tile's 1-degree blocks predicts the other half (and vice versa); the score
    is the summed absolute error of the predicted VIIRS totals."""
    ut, first, tinv = np.unique(tk, return_index=True, return_inverse=True)
    kpt = kp_row[first]                         # parent factor is constant within a tile
    nt = len(ut)
    sums = {}
    for f in (0, 1):
        w = blk == f
        sums[f] = (np.bincount(tinv, weights=np.where(w, E, 0.0), minlength=nt),
                   np.bincount(tinv, weights=np.where(w, Y, 0.0), minlength=nt))
    (EA, YA), (EB, YB) = sums[0], sums[1]
    tot = EA + EB
    med = float(np.median(tot[tot > 0])) if (tot > 0).any() else 1.0
    grid = np.concatenate([[0.0], med * 10.0 ** LAM_GRID_DECADES])
    both = (EA > 0) & (EB > 0)
    if not both.any():
        return float(med), grid
    EA, YA, EB, YB, kp = EA[both], YA[both], EB[both], YB[both], kpt[both]
    errs = [np.abs(YB - _clip_k(_shrunk(YA, EA, kp, lam), kc) * EB).sum()
            + np.abs(YA - _clip_k(_shrunk(YB, EB, kp, lam), kc) * EA).sum() for lam in grid]
    return float(grid[int(np.argmin(errs))]), grid


def _fit_regional(lat, lon, E, Y, levels, kc, lam=None, cv_block=CV_BLOCK, support_frac=SUPPORT_FRAC):
    """Nested EB factors. E = exposure (MODIS or GLM prediction), Y = VIIRS.

    Level by level (coarse -> fine) each tile's factor is shrunk toward its parent's:
    k_t = (Y_t + lam * k_parent) / (E_t + lam). ``lam`` per level comes from a 2-fold
    spatial-block CV (checkerboard of blocks of ``deg * cv_block`` inside each tile), which
    measures how well a tile's k transfers to the part of the tile it was not fitted on.
    A tile's k is only applied to rows whose sub-block (``deg * support_frac``) held training
    exposure, so a tile seen only along a border does not dictate the k of an unseen region.
    """
    sE, sY = E.sum(), Y.sum()
    g = float(_clip_k(sY / sE, kc)) if sE > 0 else np.nan
    out = {"global": _f(g), "levels": []}
    if not np.isfinite(g):
        return out
    kp_row = np.full(len(E), g)
    for deg in levels:
        tk = _tile_key(lat, lon, deg)
        if lam is not None and str(deg) in lam:
            lam_l = float(lam[str(deg)])
        else:
            bk = _tile_key(lat, lon, deg * cv_block)
            blk = (bk // 100000 + bk % 100000) % 2      # checkerboard of sub-blocks
            lam_l, _ = _choose_lam(tk, blk, E, Y, kp_row, kc)
        u, inv, Et, Yt = _agg(tk, E, Y)
        kpt = kp_row[np.unique(inv, return_index=True)[1]]
        kt = _clip_k(_shrunk(Yt, Et, kpt, lam_l), kc)
        keep = (Et > 0) & (u >= 0)
        lev = {"deg": float(deg), "lam": _f(lam_l),
               "k": {_key_str(int(a)): round(float(b), 6) for a, b in zip(u[keep], kt[keep])}}
        if support_frac:
            sk = _tile_key(lat, lon, deg * support_frac)
            sup = np.unique(sk[(E > 0) & (sk >= 0)])
            lev["support_deg"] = float(deg * support_frac)
            lev["support"] = [_key_str(int(v)) for v in sup]
        out["levels"].append(lev)
        kp_row = np.where(keep[inv], kt[inv], kp_row)
    return out


def _apply_regional(reg: dict, lat, lon) -> np.ndarray:
    """Factor per row: finest stored tile whose support covers the row, else coarser, else global."""
    g = reg.get("global")
    k = np.full(len(lat), np.nan if g is None else float(g))
    for lev in reg.get("levels", []):          # coarse -> fine: finer hits overwrite
        if not lev.get("k"):
            continue
        tk = np.fromiter((_key_int(s) for s in lev["k"]), "int64", len(lev["k"]))
        tv = np.fromiter(lev["k"].values(), float, len(lev["k"]))
        v = _lookup(tk, tv, _tile_key(lat, lon, lev["deg"]))
        if lev.get("support") is not None and lev.get("support_deg"):
            sk = np.fromiter((_key_int(s) for s in lev["support"]), "int64", len(lev["support"]))
            ok = np.isfinite(_lookup(sk, np.ones(len(sk)), _tile_key(lat, lon, lev["support_deg"])))
            v = np.where(ok, v, np.nan)
        k = np.where(np.isfinite(v), v, k)
    return k


# =========================================================================== GLM
def _standardize(z, fz):
    mu = np.asarray([np.nan if v is None else v for v in fz["mean"]], float)
    sd = np.asarray([np.nan if v is None else v for v in fz["sd"]], float)
    lo = np.asarray([np.nan if v is None else v for v in fz["lo"]], float)
    hi = np.asarray([np.nan if v is None else v for v in fz["hi"]], float)
    zc = np.clip(z, lo, hi)
    s = (zc - mu) / sd
    s[~np.isfinite(s)] = 0.0                   # missing feature -> training mean
    return s


def _glm_eta(glm: dict, z) -> np.ndarray:
    names = glm["features"]["names"]
    z = z[:, [FEATURES.index(f) for f in names]] if z.shape[1] else np.zeros((len(z), len(names)))
    s = _standardize(z, glm["features"])
    beta = np.asarray([0.0 if b is None else b for b in glm["beta"]], float)
    return float(glm["intercept"]) + s @ beta


def _fit_glm(P: dict, unit_deg: float, kc, features=DEFAULT_FEATURES):
    """Poisson pseudo-likelihood: E[V_u] = sum_{r in u} x_r exp(b0 + beta . z_r)."""
    pos = P["x"] > 0
    if not pos.any() or P["y"].sum() <= 0:
        return None
    use = [FEATURES.index(f) for f in features]
    z = P["z"][:, use]
    # unit = tile x period; VIIRS mass of x == 0 rows stays in its unit
    unit = _tile_key(P["lat"], P["lon"], unit_deg) * 100000 + P["pcode"]
    u, inv = np.unique(unit, return_inverse=True)
    Yu = np.bincount(inv, weights=P["y"], minlength=len(u))
    has = np.bincount(inv, weights=pos.astype(float), minlength=len(u)) > 0
    zp, xp, ip = z[pos], P["x"][pos], inv[pos]
    fz = {"names": list(features), "mean": [], "sd": [], "lo": [], "hi": []}
    for j in range(zp.shape[1]):
        c = zp[:, j]
        ok = np.isfinite(c)
        if ok.sum() < 2 or np.nanstd(c[ok]) == 0:
            fz["mean"].append(None); fz["sd"].append(None); fz["lo"].append(None); fz["hi"].append(None)
            continue
        w = xp[ok]
        m = float(np.average(c[ok], weights=w))
        fz["mean"].append(m)
        fz["sd"].append(float(np.sqrt(np.average((c[ok] - m) ** 2, weights=w))) or 1.0)
        lo, hi = np.quantile(c[ok], [0.001, 0.999])
        fz["lo"].append(float(lo)); fz["hi"].append(float(hi))
    S = _standardize(zp, fz)
    X = np.column_stack([np.ones(len(xp)), S])
    p = X.shape[1]
    Yh = Yu[has]
    uid = np.cumsum(has) - 1                       # unit index among units with MODIS
    iu = uid[ip]
    nu = int(has.sum())
    theta = np.zeros(p)
    theta[0] = math.log(Yh.sum() / xp.sum())

    def evaluate(t):
        e = xp * np.exp(np.clip(X @ t, -20, 20))
        mu = np.bincount(iu, weights=e, minlength=nu)
        mu = np.maximum(mu, 1e-300)
        ll = float((Yh * np.log(mu) - mu).sum())
        return e, mu, ll

    e, mu, ll = evaluate(theta)
    for _ in range(50):
        J = np.column_stack([np.bincount(iu, weights=e * X[:, j], minlength=nu) for j in range(p)])
        grad = J.T @ (Yh / mu - 1.0)
        info = (J / mu[:, None]).T @ J
        info += RIDGE * np.trace(info) / p * np.eye(p)
        try:
            step = np.linalg.solve(info, grad)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(info, grad, rcond=None)[0]
        t = 1.0
        while t > 1e-4:
            e2, mu2, ll2 = evaluate(theta + t * step)
            if ll2 >= ll - 1e-9 * abs(ll):
                break
            t /= 2
        theta = theta + t * step
        done = abs(ll2 - ll) <= 1e-10 * abs(ll) + 1e-12
        e, mu, ll = e2, mu2, ll2
        if done:
            break
    lost = float(Yu[~has].sum() / Yu.sum()) if Yu.sum() > 0 else 0.0
    # absorb VIIRS mass of units without MODIS into the intercept (keeps totals exact)
    adj = math.log(Yu.sum() / Yh.sum()) if Yh.sum() > 0 else 0.0
    return {"unit_deg": float(unit_deg), "intercept": float(theta[0] + adj),
            "beta": [_f(b) for b in theta[1:]], "features": fz,
            "lost_mass_share": _f(lost), "n_units": nu}


# =========================================================================== fit / apply
def _fit_core(name, P, metric, cfg, opts) -> dict:
    kc = tuple(opts.get("k_clip", K_CLIP))
    levels = tuple(opts.get("region_levels_deg", cfg.region_levels_deg))
    x, y = P["x"], P["y"]
    sx, sy = x.sum(), y.sum()
    core = {"n_train": int(((x > 0) | (y > 0)).sum()), "sum_modis": _f(sx), "sum_viirs": _f(sy)}
    if sx <= 0:
        core["degenerate"] = True
        return core
    if sy <= 0:                                     # VIIRS saw nothing: predict 0 (k floor)
        core.update(zero=True)
        return core
    if name == "ratio_global":
        core["k"] = _f(_clip_k(sy / sx, kc))
    elif name == "ratio_regional":
        core["regional"] = _fit_regional(P["lat"], P["lon"], x, y, levels, kc, opts.get("lam"),
                                         opts.get("cv_block", CV_BLOCK), opts.get("support_frac", SUPPORT_FRAC))
    else:
        glm = _fit_glm(P, float(opts.get("unit_deg", GLM_UNIT_DEG)), kc,
                       tuple(opts.get("features", DEFAULT_FEATURES)))
        if glm is None:
            core["degenerate"] = True
            return core
        core["glm"] = glm
        if name == "glm_regional":
            e = np.where(x > 0, x * np.exp(np.clip(_glm_eta(glm, P["z"]), -20, 20)), 0.0)
            core["regional"] = _fit_regional(P["lat"], P["lon"], e, y, levels, RESID_CLIP, opts.get("lam"),
                                             opts.get("cv_block", CV_BLOCK), opts.get("support_frac", SUPPORT_FRAC))
    return core


def fit_model(name: str, paired: pd.DataFrame, metric: str, cfg: Config | None = None, **opts) -> dict:
    """Fit ``name`` on a §4 paired table for ``metric``. Never raises on degenerate input
    (empty, all-zero, NaN): it returns params flagged ``degenerate`` whose predictions are NaN.

    opts: ``k_clip`` (lo, hi), ``region_levels_deg``, ``unit_deg`` (GLM unit), ``features``,
    ``lam`` ({str(deg): weight} to skip the CV), ``min_pairs`` (D/N sub-fit threshold).
    """
    if name not in MODELS:
        raise ValueError(f"unknown model {name!r}; choose from {MODELS}")
    cfg = cfg or Config()
    if "modis_source" in paired.columns and paired["modis_source"].nunique() > 1:
        warnings.warn("fit_model: paired table mixes several modis_source values; pooling them",
                      RuntimeWarning, stacklevel=2)
    P = paired if isinstance(paired, dict) else _rows(paired, metric, "modis_", with_y=True)
    return _fit_prepared(name, P, metric, cfg, opts)


def _fit_prepared(name, P, metric, cfg, opts) -> dict:
    kc = tuple(opts.get("k_clip", K_CLIP))
    params = {"model": name, "metric": metric, "k_clip": [float(kc[0]), float(kc[1])],
              "cap_days": metric == "fire_cell_days", "by_daynight": {}}
    dns = [d for d in pd.unique(P["dn"])] or ["ALL"]
    for dn in dns:
        sub = _subset(P, P["dn"] == dn)
        params["by_daynight"][str(dn)] = _fit_core(name, sub, metric, cfg, opts)
    params["n_train"] = int(sum(v["n_train"] for v in params["by_daynight"].values()))
    params["degenerate"] = all(v.get("degenerate") for v in params["by_daynight"].values())
    if params["degenerate"]:
        warnings.warn(f"fit_model({name}, {metric}): degenerate input (no MODIS mass); "
                      "predictions will be NaN", RuntimeWarning, stacklevel=3)
    return params


def _apply_core(core: dict, name: str, R: dict, kc) -> np.ndarray:
    x = R["x"]
    if core.get("degenerate"):
        return np.full(len(x), np.nan)
    if core.get("zero"):
        return np.zeros(len(x))
    if name == "ratio_global":
        k = np.full(len(x), np.nan if core.get("k") is None else float(core["k"]))
    else:
        k = np.ones(len(x))
        if "glm" in core:
            k = np.exp(np.clip(_glm_eta(core["glm"], R["z"]), -20, 20))
        if "regional" in core:
            k = k * _apply_regional(core["regional"], R["lat"], R["lon"])
    return np.where(x > 0, _clip_k(k, kc) * x, 0.0)


def apply_model(params: dict, modis_rows: pd.DataFrame, metric: str | None = None) -> np.ndarray:
    """MODIS rows (§3 shape, no VIIRS needed) -> VIIRS-equivalent ``metric`` per row (>= 0).

    Rows whose ``daynight`` has no sub-model use ``ALL`` (else the first available one).
    Columns prefixed ``modis_`` (a §4 paired table) are also accepted when the bare name
    is absent. Degenerate params give NaN.
    """
    metric = metric or params.get("metric")
    name = params.get("model")
    if name not in MODELS:
        raise ValueError(f"unknown model in params: {name!r}")
    n = len(modis_rows)
    if n == 0:
        return np.zeros(0)
    prefix = "" if metric in modis_rows.columns or f"modis_{metric}" not in modis_rows.columns else "modis_"
    R = _rows(modis_rows, metric, prefix, with_y=False)
    kc = tuple(params.get("k_clip", K_CLIP))
    subs = params.get("by_daynight", {})
    if not subs:
        return np.full(n, np.nan)
    fallback = "ALL" if "ALL" in subs else next(iter(subs))
    out = np.zeros(n)
    dn = R["dn"]
    for d in pd.unique(dn):
        m = dn == d
        core = subs.get(str(d), subs[fallback])
        out[m] = _apply_core(core, name, _subset(R, m), kc)
    if params.get("cap_days", metric == "fire_cell_days"):
        cap = np.where(np.isfinite(R["days"]), R["days"], np.inf)
        out = np.minimum(out, cap)
    return out


# =========================================================================== coefficients JSON
def _split_sources(paired_by_source) -> dict:
    if isinstance(paired_by_source, pd.DataFrame):
        if "modis_source" not in paired_by_source.columns:
            return {MODIS_ALL: paired_by_source}
        return {str(s): g for s, g in paired_by_source.groupby("modis_source", observed=True, sort=False)}
    return dict(paired_by_source)


def _year_of(df: pd.DataFrame) -> np.ndarray:
    if "year" in df.columns:
        return pd.to_numeric(df["year"], errors="coerce").fillna(-1).astype("int64").to_numpy()
    return pd.to_numeric(df["period"].astype(str).str[:4], errors="coerce").fillna(-1).astype("int64").to_numpy()


MAX_LODO_DOMAINS = 30
N_DOMAIN_FOLDS = 10
DOMAIN_FOLD_SEED = 20240101


def _domain_kfold(dom: np.ndarray, df: pd.DataFrame, k: int = N_DOMAIN_FOLDS,
                  seed: int = DOMAIN_FOLD_SEED) -> np.ndarray:
    """Group label per row: domains in ``k`` folds balanced by VIIRS detections (greedy,
    seeded shuffle for ties). Kept local so calibration stays independent of validate.py."""
    v = df["viirs_n_hotspots"].to_numpy(float) if "viirs_n_hotspots" in df else np.ones(len(df))
    vol = pd.Series(v).groupby(dom).sum()
    names = np.array(sorted(vol.index), dtype=object)
    vals = vol.reindex(names).to_numpy(float)
    perm = np.random.default_rng(seed).permutation(len(names))
    order = perm[np.argsort(-vals[perm], kind="stable")]
    load, cnt, fmap = np.zeros(k), np.zeros(k, np.int64), {}
    for i in order:
        f = int(np.lexsort((cnt, load))[0])
        fmap[names[i]] = f"fold{f}"
        load[f] += vals[i]
        cnt[f] += 1
    return pd.Series(dom).map(fmap).to_numpy(object)


def _groups(df: pd.DataFrame, cfg: Config, holdout: str = "domain") -> tuple[np.ndarray, str]:
    """Hold-out groups: domains (countries) if >= 3, else 10-degree spatial blocks;
    ``holdout="year"`` gives leave-one-year-out instead."""
    if holdout == "year":
        return _year_of(df).astype(str).astype(object), "year"
    if "domain" in df.columns and df["domain"].nunique() >= 3:
        dom = df["domain"].astype(str).to_numpy()
        if df["domain"].nunique() > MAX_LODO_DOMAINS:   # ~200 countries: grouped K-fold
            return _domain_kfold(dom, df), "domain_kfold"
        return dom, "domain"
    k = _tile_key(df["cell_lat"].to_numpy(float), df["cell_lon"].to_numpy(float), 10.0)
    return np.array([_key_str(int(v)) if v >= 0 else "?" for v in k], dtype=object), "block10"


def stability_table(paired_by_source, cfg: Config, metrics=METRICS, models=MODELS,
                    sources=SELECTION_SOURCES, daynights=SELECTION_DAYNIGHT, holdout="domain",
                    **opts) -> pd.DataFrame:
    """Leave-one-domain-out: for each held-out domain, fit on the others and predict the
    domain's MODIS rows. One row per (metric, model, modis_source, daynight, domain, year) with
    observed VIIRS/MODIS totals, predicted total and ``bias`` = pred / VIIRS - 1. ``modis_raw``
    is included as a baseline model."""
    by_src = _split_sources(paired_by_source)
    recs = []
    for src in sources:
        if src not in by_src:
            continue
        df_s = by_src[src]
        for dn in daynights:
            df = df_s[df_s["daynight"].astype(str) == dn] if "daynight" in df_s.columns else df_s
            if df.empty:
                continue
            grp, gkind = _groups(df, cfg, holdout)
            year = _year_of(df)
            dom = df["domain"].astype(str).to_numpy(object) if "domain" in df.columns else grp
            ug = pd.unique(grp)
            if len(ug) < 2:
                continue
            for metric in metrics:
                P = _rows(df, metric, "modis_", with_y=True)
                rows_m = df  # apply_model reads modis_ columns directly
                for g in ug:
                    te = grp == g
                    Ptr = _subset(P, ~te)
                    te_rows = rows_m[te]
                    y_te, x_te, yr_te = P["y"][te], P["x"][te], year[te]
                    preds = {"modis_raw": x_te}
                    for name in models:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            prm = _fit_prepared(name, Ptr, metric, cfg, opts)
                            preds[name] = apply_model(prm, te_rows, metric)
                    dom_te = dom[te] if gkind in ("year", "domain_kfold") else np.full(te.sum(), g, dtype=object)
                    rep = pd.DataFrame({"d": dom_te, "y": yr_te}).groupby(["d", "y"], sort=True).indices
                    for (dv, yv), ix in rep.items():
                        V, M = float(y_te[ix].sum()), float(x_te[ix].sum())
                        for name, pr in preds.items():
                            pt = float(np.nansum(pr[ix]))
                            recs.append({"metric": metric, "model": name, "modis_source": src,
                                         "daynight": dn, "holdout": gkind, "domain": dv,
                                         "year": int(yv), "viirs_total": V, "modis_total": M,
                                         "pred_total": pt,
                                         "bias": pt / V - 1 if V > 0 else np.nan,
                                         "k_obs": V / M if M > 0 else np.nan,
                                         "k_pred": pt / M if M > 0 else np.nan})
    return pd.DataFrame.from_records(recs)


def summarize_stability(stab: pd.DataFrame) -> pd.DataFrame:
    """Per (metric, model, source, daynight): median / p90 / max |domain-year bias|, pooled bias."""
    if stab is None or stab.empty:
        return pd.DataFrame()
    s = stab.assign(abs_bias=stab["bias"].abs())
    keys = [c for c in ("holdout", "metric", "model", "modis_source", "daynight") if c in s.columns]
    g = s.groupby(keys, sort=False)
    out = g.agg(n=("abs_bias", "count"), median_abs_bias=("abs_bias", "median"),
                p90_abs_bias=("abs_bias", lambda v: float(np.nanquantile(v, 0.9)) if v.notna().any() else np.nan),
                max_abs_bias=("abs_bias", "max"), pred=("pred_total", "sum"),
                viirs=("viirs_total", "sum")).reset_index()
    out["pooled_bias"] = out["pred"] / out["viirs"] - 1
    return out.drop(columns=["pred", "viirs"])


def _recommend(summary: pd.DataFrame) -> dict:
    cand = summary[summary["model"].isin(MODELS) & summary["p90_abs_bias"].notna()]
    if cand.empty:
        return {"metric": "fire_cell_days", "model": "ratio_global",
                "reason": "no leave-one-domain-out evaluation possible (fewer than 2 groups); "
                          "defaulting to the global ratio"}
    best = cand["p90_abs_bias"].min()
    tied = cand[cand["p90_abs_bias"] <= best + SELECTION_TOL].copy()
    tied["_s"] = tied["model"].map(MODEL_SIMPLICITY)
    r = tied.sort_values(["_s", "p90_abs_bias"]).iloc[0]
    rg = cand[(cand["metric"] == r["metric"]) & (cand["model"] == "ratio_global")]
    base = f"; ratio_global p90 {rg['p90_abs_bias'].iloc[0]:.1%}" if len(rg) else ""
    return {"metric": r["metric"], "model": r["model"],
            "reason": (f"lowest 90th-percentile |annual bias| per held-out domain-year under "
                       f"leave-one-domain-out ({r['modis_source']}, {r['daynight']}): p90 "
                       f"{r['p90_abs_bias']:.1%}, median {r['median_abs_bias']:.1%}{base}; "
                       f"simplest model within {SELECTION_TOL:.0%} of the best")}


def fit_all(paired_by_source, cfg: Config, training_meta: dict | None = None,
            stability: pd.DataFrame | None = None, metrics=METRICS, models=MODELS, **opts) -> dict:
    """Fit every metric x model x modis_source x daynight and build the §5 JSON.

    ``stability`` (output of :func:`stability_table`) is computed if not given; it drives
    ``recommended`` and is summarised under ``selection``.
    """
    by_src = _split_sources(paired_by_source)
    coefs = []
    for src, df in by_src.items():
        if df is None or df.empty:
            continue
        for metric in metrics:
            P = _rows(df, metric, "modis_", with_y=True)
            for dn in [d for d in DAYNIGHT if (P["dn"] == d).any()]:
                Pd = _subset(P, P["dn"] == dn)
                if dn != "ALL" and int((Pd["x"] > 0).sum()) < int(opts.get("min_pairs", cfg.min_pairs_for_split_fit)):
                    continue                        # apply falls back to ALL
                for name in models:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        prm = _fit_prepared(name, Pd, metric, cfg, opts)
                    coefs.append({"metric": metric, "model": name, "modis_source": str(src),
                                  "daynight": dn, "params": prm, "n_train": prm["n_train"]})
    if stability is None or "bias" not in getattr(stability, "columns", []):
        stability = stability_table(by_src, cfg, metrics=metrics, models=models, **opts)
    summary = summarize_stability(stability)
    meta = dict(training_data={"source_files": [], "domains": [], "periods": [], "years": []})
    tm = dict(training_meta or {})
    allp = pd.concat([d[[c for c in ("domain", "period") if c in d.columns]] for d in by_src.values()]) \
        if by_src else pd.DataFrame()
    if "domain" in allp:
        tm.setdefault("domains", sorted(allp["domain"].astype(str).unique().tolist()))
    if "period" in allp:
        per = sorted(allp["period"].astype(str).unique().tolist())
        tm.setdefault("periods", per)
        tm.setdefault("years", sorted({int(p[:4]) for p in per if p[:4].isdigit()}))
    meta["training_data"].update(tm)
    return {
        "schema_version": 2,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": cfg.to_dict(),
        **meta,
        "recommended": _recommend(summary),
        "selection": {"scheme": "leave-one-domain-out", "criterion": "p90 |annual bias| per domain-year",
                      "summary": [{k: (_f(v) if isinstance(v, (float, np.floating)) else
                                       (int(v) if isinstance(v, (np.integer,)) else v))
                                   for k, v in r.items()} for r in summary.to_dict("records")]},
        "coefficients": coefs,
    }


def _find(coefs, metric, model, src, dn):
    for c in coefs:
        if c["metric"] == metric and c["model"] == model and c["modis_source"] == src and c["daynight"] == dn:
            return c
    return None


def apply_coefficients(coef: dict, metric: str, modis_rows: pd.DataFrame, cfg: Config | None = None,
                       model: str | None = None) -> np.ndarray:
    """Apply the coefficients JSON to §3 MODIS rows, dispatching each row on ``source`` (the
    MODIS configuration) and ``daynight``. Missing D/N -> ALL; missing MODIS_TERRA/AQUA ->
    MODIS_ALL (with a warning). ``model`` defaults to the recommended model."""
    model = model or coef.get("recommended", {}).get("model") or "ratio_global"
    n = len(modis_rows)
    out = np.full(n, np.nan)
    if n == 0:
        return np.zeros(0)
    coefs = coef.get("coefficients", [])
    src = _str(modis_rows, "source", n, MODIS_ALL)
    dn = _str(modis_rows, "daynight", n, "ALL")
    keys = pd.DataFrame({"s": src, "d": dn})
    for (s, d), idx in keys.groupby(["s", "d"], sort=False).indices.items():
        s_use = s if s in MODIS_CONFIGS else MODIS_ALL
        entry = None
        for s_try in dict.fromkeys([s_use, MODIS_ALL]):
            for d_try in dict.fromkeys([d, "ALL"]):
                entry = _find(coefs, metric, model, s_try, d_try)
                if entry is not None:
                    break
            if entry is not None:
                if s_try != s:
                    warnings.warn(f"apply_coefficients: no {metric}/{model} entry for {s}; "
                                  f"using {s_try}", RuntimeWarning, stacklevel=2)
                break
        if entry is None:
            warnings.warn(f"apply_coefficients: no {metric}/{model} coefficients for ({s}, {d}); NaN",
                          RuntimeWarning, stacklevel=2)
            continue
        out[idx] = apply_model(entry["params"], modis_rows.iloc[idx], metric)
    return out
