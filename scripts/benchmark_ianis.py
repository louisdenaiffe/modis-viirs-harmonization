"""Export our MODIS-only predictions for Ianis's benchmark (origin/ianis_harmonization,
harmonizare/BENCHMARK/BENCHMARK.md): VIIRS-scale back-cast of 2018-2023 from MODIS alone, with
coefficients fitted on 2012-2017 only.

    python scripts/benchmark_ianis.py fit    WORK PA PB [--jobs 6]
    python scripts/benchmark_ianis.py export WORK HALF_A_DIR HALF_B_DIR

fit     for the training sets "all" (halves A + B) and "A" (half A only), periods < 2018:
        glm_cell and glm_regional, n_hotspots and frp_sum, day and night, the three MODIS
        configurations -> WORK/coef_{all,A}.json
export  MODIS points of 2018-2023 from HALF_*_DIR/hotspots_clean.parquet -> the pipeline's
        ``modis_as_viirs_equivalent`` (harmonized._calibrated: every MODIS point, dispatched by
        MODIS configuration, no VIIRS used) -> WORK/pred_{model}_{trainset}.parquet with
        ix, iy, year, month, daynight, pred_n, pred_frp. Train set "A" is exported for the
        half-B points only (countries the model never saw).
"""
import argparse
import json
import multiprocessing as mp
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as pads

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harmonize import calibrate as cal  # noqa: E402
from harmonize.aggregate import _nx, run_selections  # noqa: E402
from harmonize.config import Config  # noqa: E402
from harmonize.harmonized import _calibrated  # noqa: E402
from harmonize.pipeline import load_paired  # noqa: E402

MODELS = ("glm_cell", "glm_regional")
METRICS = {"n_hotspots": "pred_n", "frp_sum": "pred_frp"}
_C = {}


def _fit(key):
    ts, src, dn, metric, model = key
    df = _C[(ts, src)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prm = cal.fit_model(model, df[df["daynight"] == dn], metric, Config())
    return {"metric": metric, "model": model, "modis_source": src, "daynight": dn, "params": prm,
            "n_train": prm["n_train"], "trainset": ts}


def fit(work, pa, pb, jobs):
    for ts, paths in (("all", [pa, pb]), ("A", [pa])):
        for src, df in load_paired(paths).items():
            df = df[df["daynight"].isin(["D", "N"]) & (df["period"].astype(str) < "2018")]
            _C[(ts, src)] = df.assign(daynight=df["daynight"].astype(str)).reset_index(drop=True)
    keys = [(ts, src, dn, m, mod) for (ts, src) in _C for dn in "DN" for m in METRICS for mod in MODELS]
    with mp.get_context("fork").Pool(jobs) as pool:
        res = pool.map(_fit, keys)
    for ts in ("all", "A"):
        (work / f"coef_{ts}.json").write_text(json.dumps(
            {"training": "periods 2012-01..2017-12, " + ("halves A + B" if ts == "all" else "half A only"),
             "coefficients": [r for r in res if r["trainset"] == ts]}, default=str))
        print(ts, sum(r["trainset"] == ts for r in res), "fits")


def _points(half_dir):
    ds = pads.dataset(f"{half_dir}/hotspots_clean.parquet")
    cols = ["source", "latitude", "longitude", "acq_date", "daynight", "frp", "scan", "bright_mir_k",
            "domain", "modis_config"]
    t = ds.to_table(columns=cols, filter=pads.field("source").isin(["MODIS_TERRA", "MODIS_AQUA"])).to_pandas()
    t = t[t["acq_date"].astype(str) >= "2018-01-01"].reset_index(drop=True)
    t["acq_date"] = t["acq_date"].astype(str)
    return t


def export(work, dir_a, dir_b):
    cfg = Config()
    nx = _nx(cfg.cell_size_deg)
    out = {}
    for half, d in (("A", dir_a), ("B", dir_b)):
        pts = _points(d)
        raw = run_selections(pts, cfg, [("eq", True, lambda b, _: b["terra"] | b["aqua"])])["eq"]
        print(half, len(pts), "MODIS points 2018+,", len(raw), "config rows", flush=True)
        for ts in (("all",) if half == "A" else ("all", "A")):
            coef = json.loads((work / f"coef_{ts}.json").read_text())
            for model in MODELS:
                parts = None
                for metric, name in METRICS.items():
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        p = _calibrated(raw, cfg, coef, metric, model, name)
                    parts = p if parts is None else parts.merge(p, on=["key", "daynight"], how="outer")
                parts = parts[parts["daynight"].isin(["D", "N"])]
                key = parts["key"].to_numpy("int64")
                cell, pcode = (key // 10 ** 8) // 4, key % 10 ** 8
                o = pd.DataFrame({"ix": (cell % nx).astype("int16"), "iy": (cell // nx).astype("int16"),
                                  "year": (pcode // 100).astype("int16"), "month": (pcode % 100).astype("int16"),
                                  "daynight": parts["daynight"].to_numpy(),
                                  "pred_n": parts["pred_n"].fillna(0).to_numpy(),
                                  "pred_frp": parts["pred_frp"].fillna(0).to_numpy()})
                out.setdefault((model, ts), []).append(o)
    for (model, ts), fr in out.items():
        o = pd.concat(fr).groupby(["ix", "iy", "year", "month", "daynight"], as_index=False).sum()
        o.to_parquet(work / f"pred_{model}_{ts}.parquet", index=False)
        print(model, ts, len(o), "rows; pred_n", round(o.pred_n.sum()), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd"), ap.add_argument("work"), ap.add_argument("a"), ap.add_argument("b")
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    w = Path(a.work)
    w.mkdir(parents=True, exist_ok=True)
    fit(w, a.a, a.b, a.jobs) if a.cmd == "fit" else export(w, a.a, a.b)
