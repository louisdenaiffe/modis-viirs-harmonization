"""Per country x year x sensor: detection counts and fire-weighted centroid, straight from the
FIRMS all-country zips. Input to the A/B split (scripts/make_split.py).

    python scripts/country_stats.py data_raw/zips data_raw/country_stats.csv
"""
import re
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

PAT = re.compile(r"(modis|viirs-snpp)_(\d{4})_(.+)\.csv$")


def one_zip(path):
    rows = []
    with zipfile.ZipFile(path) as zf:
        for m in zf.namelist():
            g = PAT.search(m.split("/")[-1])
            if not g:
                continue
            sensor, year, country = g.groups()
            with zf.open(m) as f:
                d = pd.read_csv(f, usecols=["latitude", "longitude", "type"])
            t0 = d[d["type"] == 0]
            rows.append(dict(sensor=sensor, year=int(year), country=country, member=m,
                             n=len(d), n_type0=len(t0),
                             lat=d["latitude"].mean() if len(d) else float("nan"),
                             lon=d["longitude"].mean() if len(d) else float("nan"),
                             lat_min=d["latitude"].min() if len(d) else float("nan"),
                             lat_max=d["latitude"].max() if len(d) else float("nan")))
    return rows


if __name__ == "__main__":
    zips = sorted(Path(sys.argv[1]).glob("*_all_countries.zip"))
    with ProcessPoolExecutor(12) as ex:
        out = [r for rs in ex.map(one_zip, zips) for r in rs]
    pd.DataFrame(out).sort_values(["sensor", "country", "year"]).to_csv(sys.argv[2], index=False)
    print(len(out), "rows")
