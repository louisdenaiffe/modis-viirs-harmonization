"""harmonized.csv (SCHEMA §6): one VIIRS-equivalent series per (cell_id, period, daynight).

    harmonized_value = VIIRS points (VIIRS-covered days)
                     + Σ_config apply_coefficients(MODIS points from days VIIRS does NOT cover)

The MODIS part is aggregated per MODIS configuration (MODIS_ALL / MODIS_TERRA / MODIS_AQUA, from
``tag_points``) and each configuration's rows are dispatched by ``apply_coefficients`` on
``source`` (= the configuration) and ``daynight``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .aggregate import PointView, _cell_meta, _finalize, days_in_period, run_selections
from .config import Config
from .coverage import MODIS_CONFIG_LABELS, covered_day_counts, get_index, tile_codes

HARMONIZED_COLUMNS = ["cell_id", "cell_lat", "cell_lon", "period", "daynight", "domain", "metric",
                      "viirs_raw", "modis_raw", "modis_as_viirs_equivalent", "harmonized_value",
                      "source_flag", "viirs_days", "modis_only_days"]
_K = ["key", "daynight"]


def _apply(coef, metric, rows, cfg, model):
    """Agent B's calibrator, imported lazily (tests stub this function)."""
    from . import calibrate
    return calibrate.apply_coefficients(coef, metric, rows, cfg=cfg, model=model)


def _metric_rows(raw, metric, name):
    """raw selection rows -> (key, daynight, <name>, _n_<name>, _dom_<name>)."""
    cats = np.asarray(list(raw.attrs["dom_cats"]), dtype=object)
    return pd.DataFrame({
        "key": raw["key"].to_numpy("int64"), "daynight": raw["daynight"].astype(str).to_numpy(),
        name: raw[metric].to_numpy("float64"), f"_n_{name}": raw["n_hotspots"].to_numpy(),
        f"_dom_{name}": cats[raw["dom"].to_numpy("int64")] if len(raw) else np.zeros(0, object)})


def _calibrated(raw, cfg, coef, metric, model, name):
    """by-config raw rows -> Σ over configs of apply_coefficients -> (key, daynight, name)."""
    if len(raw) == 0:
        return pd.DataFrame({"key": np.zeros(0, "int64"), "daynight": pd.Series(dtype="str"),
                             name: np.zeros(0)})
    rows = _finalize(raw, "x", cfg, by_config=True)
    rows["source"] = rows["modis_config"]          # dispatch key for apply_coefficients
    ok = rows["source"].isin(list(MODIS_CONFIG_LABELS[:3])).to_numpy()
    pred = np.zeros(len(rows))
    if ok.any():
        r = rows.loc[ok].reset_index(drop=True)
        pred[ok] = np.asarray(_apply(coef, metric, r, cfg, model), dtype="float64")
    pred = np.nan_to_num(np.clip(pred, 0, None), nan=0.0)
    # strip the config from the key -> sum per (cell, period, daynight)
    key = raw["key"].to_numpy("int64")
    p = 10 ** 8
    base_key = ((key // p) // 4 * 4) * p + key % p
    return (pd.DataFrame({"key": base_key, "daynight": raw["daynight"].astype(str).to_numpy(),
                          name: pred})
            .groupby(_K, as_index=False)[name].sum())


def build_harmonized(points_tagged: pd.DataFrame, coef: dict, cfg: Config,
                     coverage=None) -> pd.DataFrame:
    """Filtered + tagged points -> harmonized table (SCHEMA §6) for ``coef['recommended']``."""
    rec = coef["recommended"]
    metric, model = rec["metric"], rec.get("model")
    pts = points_tagged
    view = PointView(pts, cfg)
    if view.conf is None:
        raise ValueError("build_harmonized needs tagged points (coverage.tag_points)")
    vcode = view.code(cfg.viirs_reference)
    is_m = lambda b, _: b["terra"] | b["aqua"]  # noqa: E731
    raws = run_selections(pts, cfg, [
        ("v", False, lambda b, _: b["src"] == vcode),
        ("m", False, is_m),
        ("eq", True, is_m),
        ("only", True, lambda b, _: (b["terra"] | b["aqua"]) & ~b["v"]),
    ], view=view)
    v = _metric_rows(raws["v"], metric, "viirs_raw")
    m = _metric_rows(raws["m"], metric, "modis_raw")
    eq = _calibrated(raws["eq"], cfg, coef, metric, model, "modis_as_viirs_equivalent")
    only = _calibrated(raws["only"], cfg, coef, metric, model, "_cal_only")
    del raws
    h = v.merge(m, on=_K, how="outer")
    h = h.merge(eq, on=_K, how="left").merge(only, on=_K, how="left")
    key = h["key"].to_numpy("int64")
    cell, pcode = (key // 10 ** 8) // 4, key % 10 ** 8
    meta = _cell_meta(cell, pcode, cfg)
    tiles = tile_codes(meta["_lat"], meta["_lon"], cfg.coverage_tile_deg)
    idx = get_index(pts, cfg, coverage)
    cnt = covered_day_counts(tiles, pcode, cfg, index=idx,
                             points_tagged=None if idx is not None else pts)
    look = pd.DataFrame({"tile": tiles, "pcode": pcode}).merge(cnt, on=["tile", "pcode"], how="left")
    vdays = look["n_viirs"].fillna(0).to_numpy("int64")
    modays = look["n_modis_only"].fillna(0).to_numpy("int64")
    mdays = look["n_modis_any"].fillna(0).to_numpy("int64")
    # a point always lies on a day its own source covers; guard against missing coverage
    vdays = np.where((vdays == 0) & h["viirs_raw"].notna().to_numpy(), 1, vdays)
    mdays = np.where((mdays == 0) & h["modis_raw"].notna().to_numpy(), 1, mdays)

    vraw = np.where(vdays > 0, h["viirs_raw"].fillna(0).to_numpy("float64"), np.nan)
    mraw = np.where(mdays > 0, h["modis_raw"].fillna(0).to_numpy("float64"), np.nan)
    eqv = np.where(mdays > 0, h["modis_as_viirs_equivalent"].fillna(0).to_numpy("float64"), np.nan)
    cal_only = h["_cal_only"].fillna(0).to_numpy("float64")
    ndays = days_in_period(pcode, cfg.time_step).astype("float64")
    if metric == "fire_cell_days":   # a cell cannot burn on more days than it was observed / exists
        cal_only = np.minimum(cal_only, modays)
        eqv = np.minimum(eqv, ndays)
    harm = np.nan_to_num(vraw, nan=0.0) + cal_only
    harm = np.where((vdays > 0) | (mdays > 0), harm, np.nan)
    if metric == "fire_cell_days":
        harm = np.minimum(harm, ndays)
    flag = np.where(vdays == 0, "MODIS_CALIBRATED", np.where(modays == 0, "VIIRS", "MIXED"))

    nv = h["_n_viirs_raw"].fillna(-1).to_numpy()
    nm = h["_n_modis_raw"].fillna(-1).to_numpy()
    dom = np.where(nv >= nm, h["_dom_viirs_raw"].to_numpy(object), h["_dom_modis_raw"].to_numpy(object))
    out = pd.DataFrame({
        "cell_id": meta["cell_id"], "cell_lat": meta["cell_lat"], "cell_lon": meta["cell_lon"],
        "period": meta["period"], "daynight": pd.array(h["daynight"].to_numpy(object), dtype="str"),
        "domain": pd.array(dom, dtype="str"),
        "metric": pd.array(np.full(len(h), metric, dtype=object), dtype="str"),
        "viirs_raw": vraw, "modis_raw": mraw, "modis_as_viirs_equivalent": eqv,
        "harmonized_value": harm, "source_flag": pd.array(flag.astype(object), dtype="str"),
        "viirs_days": vdays, "modis_only_days": modays,
    })
    return out.sort_values(["period", "daynight", "cell_id"], ignore_index=True)[HARMONIZED_COLUMNS]


def write_harmonized(harm: pd.DataFrame, out_dir) -> list[Path]:
    """harmonized.csv, plus harmonized.parquet when > 1 M rows (SCHEMA §6)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / "harmonized.csv"]
    harm.to_csv(paths[0], index=False)
    if len(harm) > 1_000_000:
        paths.append(out_dir / "harmonized.parquet")
        harm.to_parquet(paths[1], index=False)
    return paths
