#!/usr/bin/env python3
"""Download the current year's hotspots for the whole world from the NASA FIRMS API.

    python3 tools/fetch_nrt_world.py <output folder> [year]

NASA's yearly country archives stop at the end of last year; this fills the gap.
For world-size areas FIRMS returns one day per request and charges 36 "transactions"
(credits) for it, out of 5,000 per 10 minutes, so the script waits when the credit
budget runs low. About 620 requests for a full year: plan on 45-60 minutes.

- Science-quality (SP) data is used as far as it exists, near-real-time (NRT) after.
- Only points inside a country (Natural Earth outline, tools/countries_50m.geojson) are
  kept, to match the country archives, which leave out offshore detections.
- Days already downloaded are skipped, so the script can be stopped and run again.

Needs the free FIRMS MAP_KEY in the file .firms_key (or FIRMS_MAP_KEY); never printed.
Needs numpy, pandas and matplotlib (for the point-in-country test).
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import numpy as np
import pandas as pd
from matplotlib.path import Path

BASE = "https://firms.modaps.eosdis.nasa.gov"
HERE = os.path.dirname(os.path.abspath(__file__))
COST, BUDGET = 36, 4800                  # credits per world request; stay under the 5,000 limit
SENSORS = {"modis": "MODIS", "viirs-snpp": "VIIRS_SNPP"}
FIELDS = ["latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument",
          "confidence", "frp", "daynight", "type"]


def read_key():
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    path = os.path.join(os.path.dirname(HERE), ".firms_key")
    if not key and os.path.exists(path):
        key = open(path).read().strip()
    if not key:
        sys.exit("No key found. Put your FIRMS MAP_KEY in the file .firms_key in the project folder.")
    return key


def get(url, tries=4):
    """GET with retries. Errors never show the URL, because it contains the key."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):
                sys.exit(f"FIRMS answered HTTP {e.code}. Check the key.")
            err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = str(getattr(e, "reason", e))
        time.sleep(15 * (i + 1))
    sys.exit(f"FIRMS could not be reached after {tries} tries ({err}).")


class Countries:
    """Point-in-any-country test. Each country polygon is checked only against the
    points inside its bounding box, using matplotlib's fast point-in-polygon code."""

    def __init__(self, path):
        polys = json.load(open(path))["geometry"]["coordinates"]
        self.paths = []
        for poly in polys:
            verts, codes = [], []
            for ring in poly:
                verts += ring
                codes += [Path.MOVETO] + [Path.LINETO] * (len(ring) - 2) + [Path.CLOSEPOLY]
            v = np.array(verts)
            self.paths.append((Path(v, codes), v[:, 0].min(), v[:, 1].min(), v[:, 0].max(), v[:, 1].max()))

    def contains(self, x, y):
        inside = np.zeros(len(x), bool)
        for p, x0, y0, x1, y1 in self.paths:
            m = ~inside & (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
            if m.any():
                inside[m] = p.contains_points(np.column_stack([x[m], y[m]]))
        return inside


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out_dir = sys.argv[1]
    year = int(sys.argv[2]) if len(sys.argv) > 2 else date.today().year
    key = read_key()
    land = Countries(os.path.join(HERE, "countries_50m.geojson"))
    os.makedirs(out_dir, exist_ok=True)

    avail = {}
    for r in pd.read_csv(io.StringIO(get(f"{BASE}/api/data_availability/csv/{key}/ALL"))).itertuples():
        avail[r.data_id] = (date.fromisoformat(r.min_date), date.fromisoformat(r.max_date))
    status = lambda: json.loads(get(f"{BASE}/mapserver/mapkey_status/?MAP_KEY={key}"))["current_transactions"]

    start, end = date(year, 1, 1), min(date.today(), date(year, 12, 31))
    jobs = []                                     # (sensor name, source, day)
    for name, product in SENSORS.items():
        sp, nrt = avail.get(product + "_SP"), avail.get(product + "_NRT")
        sp_last = min(sp[1], end) if sp else start - timedelta(days=1)
        day = start
        while day <= end:
            if day <= sp_last:
                jobs.append((name, product + "_SP", day))
            elif nrt and nrt[0] <= day <= nrt[1]:
                jobs.append((name, product + "_NRT", day))
            day += timedelta(days=1)

    done_path = os.path.join(out_dir, f".done_{year}.txt")
    done = set(open(done_path).read().split()) if os.path.exists(done_path) else set()
    todo = [j for j in jobs if f"{j[0]}:{j[2]}" not in done]
    print(f"{len(jobs)} days to fetch, {len(jobs) - len(todo)} already done", flush=True)
    used, t0 = status(), time.time()
    for i, (name, source, day) in enumerate(todo):
        while used + COST > BUDGET:              # wait for the 10-minute credit window to roll over
            time.sleep(30)
            used = status()
        text = get(f"{BASE}/api/area/csv/{key}/{source}/world/1/{day.isoformat()}")
        used += COST
        if not text.lstrip().startswith("latitude"):
            sys.exit(f"Unexpected answer for {source} {day}: {text.strip()[:120]}")
        df = pd.read_csv(io.StringIO(text), dtype=str)
        kept, seen = 0, len(df)
        if len(df):
            lon = pd.to_numeric(df["longitude"], errors="coerce").to_numpy(float)
            lat = pd.to_numeric(df["latitude"], errors="coerce").to_numpy(float)
            ok = np.isfinite(lon) & np.isfinite(lat)
            ok[ok] = land.contains(lon[ok], lat[ok])
            df = df[ok]
            if "type" not in df:
                df = df.assign(type="0")
            path = os.path.join(out_dir, f"nrt_{name}_{year}_world.csv")
            df.reindex(columns=FIELDS).to_csv(path, mode="a", header=not os.path.exists(path), index=False)
            kept = len(df)
        with open(done_path, "a") as fh:
            fh.write(f"{name}:{day}\n")
        if i % 10 == 0 or i == len(todo) - 1:
            print(f"{i + 1}/{len(todo)}  {source} {day}  kept {kept:,} of {seen:,}"
                  f"  {time.time() - t0:.0f}s", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
