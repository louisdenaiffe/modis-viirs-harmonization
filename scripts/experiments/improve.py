"""Candidate improvements to glm_regional, scored with validate.py's hold-outs and tiers.py.

    python scripts/experiments/improve.py OUT_DIR PAIRED [PAIRED ...] [--variants a b] [--jobs N]
                                          [--source MODIS_ALL] [--daynight ALL] [--folds FOLDS_CSV]

Nothing in harmonize/ is changed. A variant is glm_regional (optionally with other options)
followed by multiplicative correction stages fitted on the training rows only:

  cell      one factor per 0.25 deg cell: r = (V + lam) / (E + lam), E = prediction so far
  blockD    the same per D-degree tile
  seasonD   the same per D-degree tile x season (3-month, hemisphere-aware)
  renorm    per 5 deg tile, rescale so that predicted = observed VIIRS in training (puts back
            the VIIRS mass of cells where MODIS never saw anything, as the base model does)

lam (shrinkage toward 1, in VIIRS units) is chosen per stage by an inner 2-fold CV over
even / odd training years (calibrate._choose_lam), so no hold-out information is used.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harmonize import calibrate as cal, validate as V  # noqa: E402
from harmonize.config import Config, METRICS  # noqa: E402
from tiers import tiers  # noqa: E402

DEF = cal.DEFAULT_FEATURES
VARIANTS = {
    "glm_regional": {},
    "cell": {"stages": ["cell", "renorm"]},
    "renorm": {"stages": ["renorm"]},
    "cell_norenorm": {"stages": ["cell"]},
    "block2_cell": {"stages": ["block2", "cell", "renorm"]},
    "season10": {"stages": ["season10", "renorm"]},
    "season10_cell": {"stages": ["season10", "cell", "renorm"]},
    "season5_cell": {"stages": ["season5", "cell", "renorm"]},
    "block2_season10_cell": {"stages": ["block2", "season10", "cell", "renorm"]},
    "levels_2_1": {"opts": {"region_levels_deg": (40.0, 20.0, 10.0, 5.0, 2.0, 1.0)}},
    "levels_2_1_cell": {"opts": {"region_levels_deg": (40.0, 20.0, 10.0, 5.0, 2.0, 1.0)},
                        "stages": ["cell", "renorm"]},
    "glm_season": {"opts": {"features": DEF + ("season_sin", "season_cos")}},
    "glm_season_cell": {"opts": {"features": DEF + ("season_sin", "season_cos")},
                        "stages": ["cell", "renorm"]},
}
CLIP = cal.RESID_CLIP
_SRC = {"src": "MODIS_ALL"}


def _geo(df):
    lat, lon = df["cell_lat"].to_numpy(float), df["cell_lon"].to_numpy(float)
    per = df["period"].astype(str)
    year = per.str[:4].astype(int).to_numpy()
    month = per.str[5:7].astype(int).to_numpy()
    return lat, lon, year, month


def _key(stage, lat, lon, month):
    if stage == "cell":
        return cal._tile_key(lat, lon, 0.25)
    if stage.startswith("block"):
        return cal._tile_key(lat, lon, float(stage[5:]))
    if stage.startswith("season"):
        s = ((month % 12) // 3 + 2 * (lat < 0)) % 4
        return cal._tile_key(lat, lon, float(stage[6:])) * 4 + s
    if stage == "renorm":
        return cal._tile_key(lat, lon, 5.0)
    raise ValueError(stage)


def _days(df):
    return cal._period_info(df["period"].to_numpy(object))[2]


def fit(name, tr, metric, cfg):
    spec = VARIANTS[name]
    base = cal.fit_model("glm_regional", tr, metric, cfg, **spec.get("opts", {}))
    par = {"variant": name, "base": base, "stages": []}
    if not spec.get("stages") or base.get("degenerate"):
        return par
    e = np.nan_to_num(cal.apply_model(base, V.modis_rows(tr, _SRC["src"]), metric))
    y = np.nan_to_num(tr[f"viirs_{metric}"].to_numpy(float))
    lat, lon, year, month = _geo(tr)
    for st in spec["stages"]:
        k = _key(st, lat, lon, month)
        u, inv, Et, Yt = cal._agg(k, e, y)
        if st == "renorm":
            with np.errstate(divide="ignore", invalid="ignore"):
                r = np.clip(np.where(Et > 0, Yt / Et, 1.0), 0.5, 2.0)
            lam = None
        else:
            lam, _ = cal._choose_lam(k, year % 2, e, y, np.ones(len(e)), CLIP)
            r = cal._clip_k(cal._shrunk(Yt, Et, 1.0, lam), CLIP)
        keep = Et > 0
        par["stages"].append({"stage": st, "lam": lam, "keys": u[keep], "r": r[keep]})
        e = e * np.where(keep[inv], r[inv], 1.0)
    return par


def apply(par, rows, metric):
    e = cal.apply_model(par["base"], rows, metric)
    if not par["stages"]:
        return e
    lat, lon, _, month = _geo(rows)
    for st in par["stages"]:
        r = cal._lookup(st["keys"], st["r"], _key(st["stage"], lat, lon, month))
        e = e * np.where(np.isfinite(r), r, 1.0)
    if metric == "fire_cell_days":
        e = np.minimum(e, _days(rows))
    return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"), ap.add_argument("paired", nargs="+")
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ap.add_argument("--schemes", nargs="+", default=["leave_year_out", "domain_kfold"])
    ap.add_argument("--source", default="MODIS_ALL"), ap.add_argument("--daynight", default="ALL")
    ap.add_argument("--folds", default=None), ap.add_argument("--jobs", type=int, default=13)
    a = ap.parse_args()
    _SRC["src"] = a.source
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    d = pd.concat([pd.read_parquet(p, filters=[("modis_source", "==", a.source), ("daynight", "==", a.daynight)])
                   for p in a.paired], ignore_index=True)
    for c in ("domain", "period", "cell_id", "daynight", "modis_source"):
        d[c] = d[c].astype(str)
    dfolds = None
    if a.folds:
        f = pd.read_csv(a.folds)
        f = f[(f["scheme"] == "domain_kfold") & (f["modis_source"] == a.source) & (f["daynight"] == "ALL")]
        dfolds = {dom: int(fo[7:]) for fo, doms in zip(f["fold"], f["test_domains"]) for dom in doms.split(";")}
    models = [V.BASELINE_RAW] + a.variants
    monthly, _ = V._validate_table(d, a.source, a.daynight, models, METRICS, tuple(a.schemes), fit, apply,
                                   Config(), print, domain_folds=dfolds, n_jobs=a.jobs)
    mon = pd.concat(monthly, ignore_index=True)
    keys = ["scheme", "metric", "model", "modis_source", "daynight"]
    ds = pd.concat([V.score_domain_years(g).assign(**dict(zip(keys, k))) for k, g in mon.groupby(keys, sort=False)],
                   ignore_index=True)
    ds.to_csv(out / "domain_scores.csv", index=False)
    t = tiers(ds)
    t.to_csv(out / "tiers.csv", index=False)
    pd.set_option("display.width", 250)
    for val in ("p90_abs_bias_pct", "median_abs_bias_pct"):
        print(val)
        print(t[t["model"] != "raw_modis"].pivot_table(index=["scheme", "metric", "model"], columns="tier", values=val, sort=False)[
            ["all", "ge1k", "ge10k", "baseline12_2019_2023"]].round(1).to_string())


if __name__ == "__main__":
    main()
