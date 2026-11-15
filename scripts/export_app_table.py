"""Export our MODIS -> VIIRS model as a table the web app's data build can read.

    python scripts/export_app_table.py COEF.json OUT.parquet [--clean DIR ...] [--ingest DATA_DIR ...]

--clean DIR    a pipeline output folder with ``hotspots_clean.parquet`` (filtered, tagged points)
--ingest DIR   a folder of FIRMS CSV / zip files: ingested, filtered and tagged here (MODIS only
               is enough; VIIRS files in it are ignored after tagging)

For every 0.25 degree cell x month x day/night with kept MODIS detections (type 0, confidence
>= nominal), the table gives ``n_veq``: the VIIRS-equivalent hotspot count predicted from MODIS
alone (``modis_as_viirs_equivalent`` of the pipeline, metric ``n_hotspots``, model ``glm_cell``,
the per-metric recommendation of METHOD.md section 6.10). Day and night are predicted by their own fits; each MODIS configuration
(Terra + Aqua, Terra only, Aqua only) by its own coefficients.

Columns: ix, iy, year, month, daynight, n_veq   with
lon = (ix + 0.5) * 0.25 - 180, lat = (iy + 0.5) * 0.25 - 90 (the same grid as Ianis's tables).
The web app's data build (webapp/tools/build_world.py --viirs-scale) shares n_veq between the
kept MODIS hotspots of the cell, month and day/night. The table in webapp/tables/ was made with

    python scripts/export_app_table.py outputs_full/calibration_coefficients.json \
        webapp/tables/viirs_scale_cells.parquet \
        --ingest <folder with modis_2000..2011_all_countries.zip> --clean runs/harmonized/A runs/harmonized/B
"""
import argparse
import gc
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as pads

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harmonize import coverage as cov_mod  # noqa: E402
from harmonize import ingest  # noqa: E402
from harmonize.aggregate import _nx, run_selections  # noqa: E402
from harmonize.config import Config  # noqa: E402
from harmonize.harmonized import _calibrated  # noqa: E402

METRIC, MODEL = "n_hotspots", "glm_cell"
COLS = ["source", "latitude", "longitude", "acq_date", "daynight", "frp", "scan", "bright_mir_k",
        "domain", "modis_config"]
MODIS = ["MODIS_TERRA", "MODIS_AQUA"]


def predict(pts: pd.DataFrame, coef: dict, cfg: Config) -> pd.DataFrame:
    nx = _nx(cfg.cell_size_deg)
    raw = run_selections(pts, cfg, [("eq", True, lambda b, _: b["terra"] | b["aqua"])])["eq"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = _calibrated(raw, cfg, coef, METRIC, MODEL, "n_veq")
    key = raw["key"].to_numpy("int64")
    n = (pd.DataFrame({"key": ((key // 10 ** 8) // 4 * 4) * 10 ** 8 + key % 10 ** 8,
                       "daynight": raw["daynight"].astype(str).to_numpy(),
                       "n_modis": raw["n_hotspots"].to_numpy("int64")})
         .groupby(["key", "daynight"], as_index=False)["n_modis"].sum())
    p = p.merge(n, on=["key", "daynight"], how="outer")
    p = p[p["daynight"].isin(["D", "N"])]
    key = p["key"].to_numpy("int64")
    cell, pcode = (key // 10 ** 8) // 4, key % 10 ** 8
    return pd.DataFrame({"ix": (cell % nx).astype("int16"), "iy": (cell // nx).astype("int16"),
                         "year": (pcode // 100).astype("int16"), "month": (pcode % 100).astype("int8"),
                         "daynight": p["daynight"].to_numpy(),
                         "n_modis": p["n_modis"].fillna(0).to_numpy("int32"),
                         "n_veq": p["n_veq"].fillna(0).to_numpy("float32")})


def clean_points(d):
    ds = pads.dataset(f"{d}/hotspots_clean.parquet")
    t = ds.to_table(columns=COLS, filter=pads.field("source").isin(MODIS)).to_pandas()
    t["acq_date"] = t["acq_date"].astype(str)
    return t


def ingest_points(d, cache):
    cfg = Config(data_dir=Path(d), cache_dir=Path(cache))
    allp = ingest.load_points(cfg)
    cov = cov_mod.build_coverage(allp, cfg)
    pts = ingest.apply_filters(allp, cfg)
    del allp
    gc.collect()
    pts = cov_mod.tag_points(pts, cov, cfg)
    pts = pts[pts["source"].isin(MODIS)][COLS].reset_index(drop=True)
    pts["acq_date"] = pts["acq_date"].astype(str)
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("coef"), ap.add_argument("out")
    ap.add_argument("--clean", nargs="*", default=[])
    ap.add_argument("--ingest", nargs="*", default=[])
    ap.add_argument("--cache", default=".cache")
    a = ap.parse_args()
    coef = json.loads(Path(a.coef).read_text())
    cfg = Config()
    parts = []
    for kind, dirs in (("clean", a.clean), ("ingest", a.ingest)):
        for d in dirs:
            pts = clean_points(d) if kind == "clean" else ingest_points(d, a.cache)
            years = pts["acq_date"].str[:4]
            for y in sorted(years.unique()):
                o = predict(pts[(years == y).to_numpy()].reset_index(drop=True), coef, cfg)
                parts.append(o)
                print(f"{d} {y}: {len(o):,} rows, MODIS kept {o.n_modis.sum():,} -> VIIRS-eq "
                      f"{o.n_veq.sum():,.0f}", flush=True)
            del pts
            gc.collect()
    o = pd.concat(parts).groupby(["ix", "iy", "year", "month", "daynight"], as_index=False).sum()
    o = o.sort_values(["year", "month", "daynight", "iy", "ix"]).drop(columns="n_modis")
    o["n_veq"], o["daynight"] = o["n_veq"].astype("float32"), o["daynight"].astype("category")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    o.to_parquet(a.out, index=False, compression="zstd", compression_level=19)
    print(f"{len(o):,} rows -> {a.out}; years {o.year.min()}-{o.year.max()}")


if __name__ == "__main__":
    main()
