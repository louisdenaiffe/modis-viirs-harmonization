"""Score distributions by country-year size tier, from any domain_scores.csv
(validate.py or crosstest.py output).

    python scripts/tiers.py DOMAIN_SCORES.csv OUT.csv [--split splits/country_split.csv]

The p90 over ~2700 country-years is dominated by tiny territories (a few dozen detections a
year), where |bias| of several hundred % is sampling noise. The baseline was 12 large
countries. So every combination is reported for these tiers:

- ``all``: every country-year (unfiltered; what validate.py reports).
- ``ge1k`` / ``ge10k``: country-years with >= 1 000 / >= 10 000 VIIRS detections in the same
  (modis_source, daynight) paired table.
- ``baseline12``: the 12 countries of the earlier test set, all years.
- ``baseline12_2019_2023``: the same 12 countries, 2019 and 2023 only (comparable years).

The size of a country-year is taken from its own VIIRS n_hotspots total, never from the
prediction, so the filter cannot favour a model.
"""
import argparse

import numpy as np
import pandas as pd

BASELINE12 = ["Australia", "Bolivia", "Brazil", "Canada", "Greece", "India", "Indonesia", "Italy",
              "Kazakhstan", "Mexico", "United_States", "Zambia"]
KEYS = ["scheme", "metric", "model", "modis_source", "daynight"]


def size_table(ds: pd.DataFrame) -> pd.DataFrame:
    s = ds[(ds["metric"] == "n_hotspots") & (ds["model"] == "raw_modis")]
    s = s[["scheme", "modis_source", "daynight", "domain", "year", "obs_total"]]
    return s.rename(columns={"obs_total": "viirs_detections"})


def tier_masks(d: pd.DataFrame) -> dict:
    b = d["domain"].isin(BASELINE12)
    return {"all": np.ones(len(d), bool), "ge1k": (d["viirs_detections"] >= 1_000).to_numpy(),
            "ge10k": (d["viirs_detections"] >= 10_000).to_numpy(), "baseline12": b.to_numpy(),
            "baseline12_2019_2023": (b & d["year"].isin([2019, 2023])).to_numpy()}


def tiers(ds: pd.DataFrame) -> pd.DataFrame:
    d = ds.merge(size_table(ds), on=["scheme", "modis_source", "daynight", "domain", "year"],
                 how="left")
    out = []
    for k, g in d.groupby(KEYS, sort=False):
        for tier, m in tier_masks(g).items():
            x = g[m]
            ab = x["bias_pct"].abs().dropna()
            if ab.empty:
                continue
            i = ab.idxmax()
            out.append(dict(zip(KEYS, k), tier=tier, n_domain_years=len(ab),
                            median_abs_bias_pct=ab.median(), p90_abs_bias_pct=np.percentile(ab, 90),
                            max_abs_bias_pct=ab.max(),
                            worst=f"{x.loc[i, 'domain']}-{x.loc[i, 'year']}",
                            pooled_bias_pct=100 * (x["pred_total"].sum() / x["obs_total"].sum() - 1),
                            median_r2_monthly=x["r2_monthly"].median()))
    return pd.DataFrame(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("domain_scores")
    ap.add_argument("out")
    a = ap.parse_args()
    t = tiers(pd.read_csv(a.domain_scores))
    t.to_csv(a.out, index=False)
    pd.set_option("display.width", 250)
    v = t[(t["modis_source"] == "MODIS_ALL") & (t["daynight"] == "ALL")]
    print(v.pivot_table(index=["scheme", "metric", "model"], columns="tier",
                        values="p90_abs_bias_pct").round(1).to_string())
