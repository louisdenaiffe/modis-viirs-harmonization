"""Long-gap back-cast test: fit on late years only, score earlier years (no training year on
either side of the test years, unlike leave-year-out).

    python scripts/experiments/long_gap.py OUT_DIR PAIRED [PAIRED ...] [--variants ...] [--jobs N]

Splits: train >= 2016 -> test 2012-2015 (gap 1-4 years); train >= 2019 -> test 2012-2015
(gap 4-7 years); train >= 2019 -> test 2012-2013 only (gap 6-7 years).
"""
import argparse
import multiprocessing as mp
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve as I  # noqa: E402
from improve import V, METRICS, Config, tiers  # noqa: E402

# label: (train_lo, train_hi, test_lo, test_hi)
SPLITS = {"fit2016+_test2012-15": (2016, 2024, 2012, 2015), "fit2019+_test2012-15": (2019, 2024, 2012, 2015),
          "fit2019+_test2012-13": (2019, 2024, 2012, 2013),
          "fit-2020_test2021-24": (2012, 2020, 2021, 2024), "fit-2017_test2021-24": (2012, 2017, 2021, 2024),
          "fit-2017_test2023-24": (2012, 2017, 2023, 2024), "fit2015-21_test2012-13": (2015, 2021, 2012, 2013)}
TRAINS = sorted({v[:2] for v in SPLITS.values()})
_C = {}


def _job(key):
    (y0, y1), metric, var = key
    d, year = _C["d"], _C["year"]
    tr = d[(year >= y0) & (year <= y1)]
    te = d
    x = np.nan_to_num(te[f"modis_{metric}"].to_numpy(float))
    idx = np.flatnonzero(x > 0)
    p = np.zeros(len(te))
    if var == V.BASELINE_RAW:
        p[idx] = x[idx]
    else:
        par = I.fit(var, tr, metric, Config())
        p[idx] = I.apply(par, V.modis_rows(te, I._SRC["src"]).iloc[idx], metric)
    return key, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"), ap.add_argument("paired", nargs="+")
    ap.add_argument("--variants", nargs="+", default=["glm_regional", "cell", "renorm", "block2_cell"])
    ap.add_argument("--source", default="MODIS_ALL"), ap.add_argument("--daynight", default="ALL")
    ap.add_argument("--jobs", type=int, default=14)
    a = ap.parse_args()
    I._SRC["src"] = a.source
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    d = pd.concat([pd.read_parquet(p, filters=[("modis_source", "==", a.source), ("daynight", "==", a.daynight)])
                   for p in a.paired], ignore_index=True)
    for c in ("domain", "period", "cell_id", "daynight", "modis_source"):
        d[c] = d[c].astype(str)
    year = d["period"].str[:4].astype(int).to_numpy()
    _C.update(d=d, year=year)
    te = d
    codes, keys = V._group_codes(te)
    ng = len(keys)
    jobs = [(y0, m, v) for y0 in TRAINS for m in METRICS for v in [V.BASELINE_RAW] + a.variants]
    with mp.get_context("fork").Pool(min(a.jobs, len(jobs))) as pool:
        res = dict(pool.imap_unordered(_job, jobs))
    rows = []
    for label, (a0, a1, t0, t1) in SPLITS.items():
        y0 = (a0, a1)
        for m in METRICS:
            for v in [V.BASELINE_RAW] + a.variants:
                mt = keys.copy()
                mt["obs"] = np.bincount(codes, te[f"viirs_{m}"].to_numpy(float), ng)
                mt["pred"] = np.bincount(codes, np.nan_to_num(res[(y0, m, v)]), ng)
                mt = mt[(mt["year"] >= t0) & (mt["year"] <= t1)]
                rows.append(V.score_domain_years(mt).assign(scheme=label, metric=m, model=v,
                                                            modis_source=a.source, daynight=a.daynight))
    ds = pd.concat(rows, ignore_index=True)
    ds.to_csv(out / "domain_scores.csv", index=False)
    t = tiers(ds)
    t.to_csv(out / "tiers.csv", index=False)
    pd.set_option("display.width", 250)
    t = t[t["model"] != "raw_modis"]
    for val in ("p90_abs_bias_pct", "median_abs_bias_pct", "pooled_bias_pct"):
        print(val)
        print(t[t["tier"].isin(["ge1k", "ge10k", "baseline12"])].pivot_table(
            index=["scheme", "model"], columns=["metric", "tier"], values=val, sort=False).round(1).to_string())


if __name__ == "__main__":
    main()
