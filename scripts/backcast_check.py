"""Back-cast checks (MODIS-only 2000-2011 run with the final coefficients).

    python scripts/backcast_check.py COEF.json BACKCAST_DATA_DIR BACKCAST_OUT HARM_A HARM_B OUT_DIR

1. Terra-only dispatch. The 2000-2002 back-cast files are ingested and tagged as the pipeline
   does. We count tile-days per MODIS configuration before and after Aqua's first data
   (2002-07-04), then recompute the calibrated MODIS sum for the Terra-only period twice:
   with the coefficients as they are (MODIS_TERRA entries) and with the MODIS_TERRA entries
   removed (apply_coefficients then falls back to MODIS_ALL). The pipeline's harmonized
   total must equal the first and differ from the second.
2. Continuity. Annual harmonized totals per country 2000-2024: back-cast run (2000-2011) plus
   the A/B harmonized runs (2012-2024). Steps at 2002 (Terra-only -> Terra+Aqua) and at
   2011/2012 (calibrated MODIS -> VIIRS) are reported as the effective k = harmonized / raw
   MODIS per year, because a real fire-activity change moves both.
"""
import copy
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harmonize import calibrate, coverage as cov_mod, ingest  # noqa: E402
from harmonize.aggregate import _finalize, run_selections, PointView  # noqa: E402
from harmonize.config import Config  # noqa: E402
from harmonize.harmonized import build_harmonized  # noqa: E402

AQUA_START = pd.Timestamp("2002-07-04")


def read_harm(d):
    d = Path(d)
    p = d / "harmonized.parquet"
    cols = ["cell_id", "period", "daynight", "domain", "viirs_raw", "modis_raw",
            "modis_as_viirs_equivalent", "harmonized_value", "source_flag"]
    h = pd.read_parquet(p, columns=cols) if p.exists() else pd.read_csv(d / "harmonized.csv", usecols=cols)
    return h[h["daynight"] == "ALL"]


def terra_dispatch(coef, data_dir, out):
    cfg = Config(data_dir=data_dir, out_dir=out)
    pts_all = ingest.load_points(cfg)
    yr = pts_all["acq_date"].astype(str).str[:4].astype(int)
    pts_all = pts_all[(yr >= 2000) & (yr <= 2003)].reset_index(drop=True)
    cov = cov_mod.build_coverage(pts_all, cfg)
    pts = cov_mod.tag_points(ingest.apply_filters(pts_all, cfg), cov, cfg)
    day = pd.to_datetime(pts["acq_date"].astype(str))
    pre = day < AQUA_START
    tab = pd.crosstab(np.where(pre, "before 2002-07-04", "from 2002-07-04"),
                      pts["modis_config"].astype(str))
    no_terra = copy.deepcopy(coef)
    no_terra["coefficients"] = [c for c in no_terra["coefficients"] if c["modis_source"] != "MODIS_TERRA"]
    sub = pts[pre.to_numpy()].reset_index(drop=True)
    sub.attrs = pts.attrs
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        h_real = build_harmonized(sub, coef, cfg, coverage=cov)
        h_fallback = build_harmonized(sub, no_terra, cfg, coverage=cov)
    # whole months only (Jan 2000 - Jun 2002), to compare with the pipeline's own table
    a = h_real[(h_real["daynight"] == "ALL") & (h_real["period"].astype(str) < "2002-07")]
    b = h_fallback[(h_fallback["daynight"] == "ALL") & (h_fallback["period"].astype(str) < "2002-07")]
    return tab, dict(metric=coef["recommended"]["metric"], model=coef["recommended"]["model"],
                     terra_only_points=int(len(sub)),
                     raw_modis=float(a["modis_raw"].sum()),
                     calibrated_with_terra_entries=float(a["harmonized_value"].sum()),
                     calibrated_with_modis_all_fallback=float(b["harmonized_value"].sum()))


if __name__ == "__main__":
    coef_p, bdata, bout, harm_a, harm_b, out = sys.argv[1:7]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    coef = json.loads(Path(coef_p).read_text())
    tab, d = terra_dispatch(coef, bdata, Path(bout) / "_check")
    tab.to_csv(out / "backcast_terra_dispatch_points.csv")
    bc = read_harm(bout)
    pipeline_pre = bc[bc["period"].astype(str) < "2002-07"]
    d["pipeline_harmonized_2000_to_2002_06"] = float(pipeline_pre["harmonized_value"].sum())
    pd.Series(d).to_csv(out / "backcast_terra_dispatch.csv", header=False)
    print(tab.to_string())
    print(json.dumps(d, indent=1))

    countries = set(bc["domain"].astype(str))
    parts = [bc]
    for h in (harm_a, harm_b):
        x = read_harm(h)
        parts.append(x[x["domain"].astype(str).isin(countries)])
    allh = pd.concat(parts, ignore_index=True)
    allh["year"] = allh["period"].astype(str).str[:4].astype(int)
    ann = allh.groupby(["domain", "year"])[["harmonized_value", "modis_raw", "viirs_raw",
                                            "modis_as_viirs_equivalent"]].sum().reset_index()
    ann["k_eff"] = ann["harmonized_value"] / ann["modis_raw"]
    ann["k_modis_equiv"] = ann["modis_as_viirs_equivalent"] / ann["modis_raw"]
    ann.to_csv(out / "backcast_annual_series.csv", index=False)
    tot = ann.groupby("year")[["harmonized_value", "modis_raw", "viirs_raw", "modis_as_viirs_equivalent"]].sum()
    tot["k_eff"] = tot["harmonized_value"] / tot["modis_raw"]
    tot["k_modis_equiv"] = tot["modis_as_viirs_equivalent"] / tot["modis_raw"]
    tot.to_csv(out / "backcast_annual_total.csv")
    pd.set_option("display.width", 200)
    print(tot.round(3).to_string())
    # 2012-2024: calibrated MODIS vs actual VIIRS for these countries (in-sample: the final
    # coefficients were fitted on these years)
    v = ann[ann["year"] >= 2012].assign(bias=lambda x: 100 * (x["modis_as_viirs_equivalent"] / x["viirs_raw"] - 1))
    print("in-sample 2012-2024 |bias| median/p90:", v["bias"].abs().median().round(1),
          np.nanpercentile(v["bias"].abs(), 90).round(1))
