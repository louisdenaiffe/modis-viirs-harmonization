"""Orbit-drift check on the paired tables.

    python scripts/drift.py OUT_DIR paired1.parquet [paired2.parquet ...] [--jobs 16]

1. ``drift_ratio.csv``: the yearly VIIRS/MODIS ratio, 2012-2024, per MODIS configuration
   (MODIS_ALL = Terra+Aqua, MODIS_TERRA, MODIS_AQUA) and metric, day+night pooled. It is given
   in two forms: ``ratio_pooled`` (sum VIIRS / sum MODIS over all countries) and
   ``ratio_median_country`` (median over the countries that have >= MIN_MODIS MODIS
   detections in every year, so a change in the regional mix cannot pass for drift).
   Also ``drift_trend.csv``: least-squares slope of log ratio per year, 2012-2019 vs
   2019-2024.
2. ``drift_lyo.csv`` / ``drift_lyo_summary.csv``: back-cast skill on held-out years
   2012-2019. For each held-out year y the model is fitted twice, on (a) every other year
   2012-2024 and (b) every other year 2012-2019 only, and scored per country-year exactly like
   validate.py (back-cast mode). This tells whether the post-2019 years (drifted orbits) help
   or hurt a pre-2020 back-cast.
"""
import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harmonize import validate as V  # noqa: E402
from harmonize.config import Config, METRICS, MODIS_CONFIGS  # noqa: E402
from harmonize.pipeline import load_paired  # noqa: E402

MIN_MODIS = 1000
CUT = 2019
_CTX = {}


def ratios(paired):
    out = []
    for src, df in paired.items():
        d = df[df["daynight"].astype(str) == "ALL"]
        yr = V.year_of(d)
        dom = d["domain"].astype(str).to_numpy()
        for m in METRICS:
            t = pd.DataFrame({"y": yr, "d": dom, "v": d[f"viirs_{m}"].to_numpy(float),
                              "x": d[f"modis_{m}"].to_numpy(float),
                              "n": d["modis_n_hotspots"].to_numpy(float)})
            pooled = t.groupby("y")[["v", "x"]].sum()
            cy = t.groupby(["d", "y"])[["v", "x", "n"]].sum()
            ok = cy["n"].unstack().ge(MIN_MODIS).all(axis=1)
            keep = cy[cy.index.get_level_values(0).isin(ok[ok].index)]
            med = (keep["v"] / keep["x"]).groupby(level=1).median()
            for y in pooled.index:
                out.append(dict(modis_source=src, metric=m, year=int(y),
                                viirs=pooled.loc[y, "v"], modis=pooled.loc[y, "x"],
                                ratio_pooled=pooled.loc[y, "v"] / pooled.loc[y, "x"],
                                ratio_median_country=med.get(y, np.nan),
                                n_countries_median=int(ok.sum())))
    return pd.DataFrame(out)


def trends(r):
    rows = []
    for (src, m), g in r.groupby(["modis_source", "metric"]):
        for lo, hi in ((2012, CUT), (CUT, 2024), (2012, 2024)):
            h = g[(g["year"] >= lo) & (g["year"] <= hi)]
            for col in ("ratio_pooled", "ratio_median_country"):
                s = np.polyfit(h["year"], np.log(h[col]), 1)[0] if len(h) > 2 else np.nan
                rows.append(dict(modis_source=src, metric=m, years=f"{lo}-{hi}", ratio=col,
                                 pct_per_year=100 * (np.exp(s) - 1)))
    return pd.DataFrame(rows)


def _job(key):
    src, y, variant, m, mod = key
    d = _CTX["tables"][src]
    yr = _CTX["years"][src]
    test = yr == y
    train = (yr != y) if variant == "all_years" else ((yr != y) & (yr <= CUT))
    x = np.nan_to_num(d[f"modis_{m}"].to_numpy(float))
    idx = np.flatnonzero(test & (x > 0))
    if mod == V.BASELINE_RAW:
        return key, idx, x[idx]
    params = _CTX["fit"](mod, d[train], m, _CTX["cfg"])
    p = np.asarray(_CTX["apply"](params, V.modis_rows(d.iloc[idx], src), m), float)
    return key, idx, p


def lyo_compare(paired, n_jobs, sources=("MODIS_ALL",)):
    names, fit, apply, backend = V.get_backend()
    models = [V.BASELINE_RAW] + list(names)
    tables, years = {}, {}
    for s in sources:
        d = paired[s]
        tables[s] = d[d["daynight"].astype(str) == "ALL"].reset_index(drop=True)
        years[s] = V.year_of(tables[s])
    held = [y for y in range(2012, CUT + 1)]
    jobs = [(s, y, v, m, mod) for s in sources for y in held for v in ("all_years", "pre2020")
            for m in METRICS for mod in models if not (mod == V.BASELINE_RAW and v == "pre2020")]
    _CTX.update(tables=tables, years=years, fit=fit, apply=apply, cfg=Config())
    t0 = time.time()
    with mp.get_context("fork").Pool(n_jobs) as pool:
        res = list(pool.imap_unordered(_job, jobs))
    print(f"lyo fits: {len(jobs)} in {time.time() - t0:.0f}s")
    monthly = []
    for (s, y, v, m, mod), idx, p in res:
        d = tables[s]
        sub = years[s] == y
        codes, keys = V._group_codes(d[sub])
        pos = np.flatnonzero(sub)
        pr = np.zeros(len(d))
        pr[idx] = p
        ng = len(keys)
        mt = keys.copy()
        mt["obs"] = np.bincount(codes, d.loc[sub, f"viirs_{m}"].to_numpy(float), ng)
        mt["pred"] = np.bincount(codes, pr[pos], ng)
        mt["variant"], mt["metric"], mt["model"], mt["modis_source"] = v, m, mod, s
        monthly.append(mt)
    mon = pd.concat(monthly, ignore_index=True)
    k = ["variant", "metric", "model", "modis_source"]
    ds, sm = [], []
    for key, g in mon.groupby(k):
        sc = V.score_domain_years(g)
        ds.append(sc.assign(**dict(zip(k, key))))
        sm.append(dict(zip(k, key), **V.distribution(sc, g)))
    return pd.concat(ds, ignore_index=True), pd.DataFrame(sm)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("paired", type=Path, nargs="+")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--skip-lyo", action="store_true")
    ap.add_argument("--sources", nargs="+", default=["MODIS_ALL"])
    ap.add_argument("--suffix", default="")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    paired = load_paired(a.paired)
    r = ratios(paired)
    r.to_csv(a.out / "drift_ratio.csv", index=False)
    t = trends(r)
    t.to_csv(a.out / "drift_trend.csv", index=False)
    pd.set_option("display.width", 200)
    print(r.pivot_table(index="year", columns=["metric", "modis_source"], values="ratio_median_country").round(3))
    print(t[t["ratio"] == "ratio_median_country"].pivot_table(index=["metric", "modis_source"], columns="years",
                                                              values="pct_per_year").round(2))
    if not a.skip_lyo:
        ds, sm = lyo_compare(paired, a.jobs, tuple(a.sources))
        ds.to_csv(a.out / f"drift_lyo{a.suffix}.csv", index=False)
        sm.to_csv(a.out / f"drift_lyo_summary{a.suffix}.csv", index=False)
        print(sm.pivot_table(index=["modis_source", "metric", "model"], columns="variant",
                             values=["p90_abs_bias_pct", "median_abs_bias_pct"]).round(1))
