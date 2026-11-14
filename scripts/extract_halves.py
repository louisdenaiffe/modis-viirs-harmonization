"""Extract per-country CSVs from the FIRMS all-country zips into data_A/<year>/ and
data_B/<year>/ (2012-2024, MODIS + VIIRS S-NPP) following splits/country_split.csv, and
MODIS 2000-2011 for BACKCAST countries into data_backcast/<year>/.

    python scripts/extract_halves.py data_raw/zips splits/country_split.csv .
"""
import re
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

PAT = re.compile(r"(modis|viirs-snpp)_(\d{4})_(.+)\.csv$")
# 2-3 countries per GFED region, from both halves
BACKCAST = ["Canada", "Russian_Federation", "United_States", "Mexico", "Honduras", "Venezuela",
            "Colombia", "Brazil", "Bolivia", "Argentina", "Spain", "Italy", "Greece", "Turkey",
            "Iran", "Nigeria", "South_Sudan", "Central_African_Republic",
            "Democratic_Republic_of_the_Congo", "Angola", "Zambia", "China", "Kazakhstan",
            "Mongolia", "India", "Myanmar", "Thailand", "Indonesia", "Papua_New_Guinea",
            "Australia", "New_Zealand"]


def one(args):
    zpath, half_of, root = args
    n = 0
    with zipfile.ZipFile(zpath) as zf:
        for m in zf.namelist():
            g = PAT.search(m.split("/")[-1])
            if not g:
                continue
            sensor, year, country = g.groups()
            y = int(year)
            if y >= 2012:
                h = half_of.get(country)
                if h is None:
                    print("NOT IN SPLIT:", m)
                    continue
                dest = Path(root) / f"data_{h}" / year
            elif sensor == "modis" and country in BACKCAST:
                dest = Path(root) / "data_backcast" / year
            else:
                continue
            dest.mkdir(parents=True, exist_ok=True)
            (dest / m.split("/")[-1]).write_bytes(zf.read(m))
            n += 1
    return zpath.name, n


if __name__ == "__main__":
    split = pd.read_csv(sys.argv[2])
    half_of = dict(zip(split["country"], split["half"]))
    missing = [c for c in BACKCAST if c not in half_of]
    assert not missing, missing
    zips = sorted(Path(sys.argv[1]).glob("*_all_countries.zip"))
    with ProcessPoolExecutor(8) as ex:
        for name, n in ex.map(one, [(z, half_of, sys.argv[3]) for z in zips]):
            print(name, n)
