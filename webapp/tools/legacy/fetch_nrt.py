#!/usr/bin/env python3
"""Download the current year's hotspots for Argentina from the NASA FIRMS API.

    python3 -I tools/fetch_nrt.py <output folder> [year]

The yearly archive files stop at the end of last year. This script fills the gap:
it asks FIRMS for every 5-day window since 1 January, for MODIS and VIIRS S-NPP,
inside a rectangle around Argentina, then keeps only the points that fall inside
Argentina's border (tools/argentina_border.geojson) so the new data matches the
country archive.

It uses "standard processing" (SP, science quality) data as far as it exists and
"near real-time" (NRT) data for the most recent weeks.

Needs a free FIRMS MAP_KEY (https://firms.modaps.eosdis.nasa.gov/api/map_key/),
read from the file .firms_key in the project folder or from the FIRMS_MAP_KEY
environment variable. The key is never printed.
"""
import csv
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

API = "https://firms.modaps.eosdis.nasa.gov/api"
HERE = os.path.dirname(os.path.abspath(__file__))
BBOX = "-73.7,-55.2,-53.5,-21.6"          # west,south,east,north around Argentina
SENSORS = {"modis": "MODIS", "viirs-snpp": "VIIRS_SNPP"}
FIELDS = ["latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument",
          "confidence", "frp", "daynight", "type"]


def read_key():
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    path = os.path.join(os.path.dirname(os.path.dirname(HERE)), ".firms_key")
    if not key and os.path.exists(path):
        key = open(path).read().strip()
    if not key:
        sys.exit("No key found. Put your FIRMS MAP_KEY in the file .firms_key in the project folder.")
    return key


def get(path):
    """GET an API path. Errors never include the URL, because the URL contains the key."""
    try:
        with urllib.request.urlopen(f"{API}/{path}", timeout=120) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        sys.exit(f"FIRMS answered with HTTP {e.code}. Check that the key is valid and has transactions left.")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach FIRMS: {e.reason}")


class Border:
    """Point-in-polygon test, sped up with a 0.1 degree grid: only cells crossed by the
    border need the exact test; every other cell is entirely inside or outside."""

    def __init__(self, path):
        geom = json.load(open(path))["geometry"]["coordinates"]
        self.rings = [ring for poly in geom for ring in poly]
        self.edge_cells, self.cache = set(), {}
        for ring in self.rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                steps = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / 0.02))
                for i in range(steps + 1):
                    cx = math.floor((x1 + (x2 - x1) * i / steps) * 10)
                    cy = math.floor((y1 + (y2 - y1) * i / steps) * 10)
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            self.edge_cells.add((cx + dx, cy + dy))

    def _exact(self, x, y):
        inside = False
        for ring in self.rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
        return inside

    def contains(self, x, y):
        cell = (math.floor(x * 10), math.floor(y * 10))
        if cell in self.edge_cells:
            return self._exact(x, y)
        hit = self.cache.get(cell)
        if hit is None:
            hit = self.cache[cell] = self._exact((cell[0] + 0.5) / 10, (cell[1] + 0.5) / 10)
        return hit


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out_dir = sys.argv[1]
    year = int(sys.argv[2]) if len(sys.argv) > 2 else date.today().year
    key = read_key()
    border = Border(os.path.join(HERE, "argentina_border.geojson"))
    os.makedirs(out_dir, exist_ok=True)

    # Which dates does each product cover?
    avail = {}
    for r in csv.DictReader(io.StringIO(get(f"data_availability/csv/{key}/ALL"))):
        try:
            avail[r["data_id"]] = (date.fromisoformat(r["min_date"]), date.fromisoformat(r["max_date"]))
        except (KeyError, ValueError):
            pass
    if not avail:
        sys.exit("FIRMS did not return its list of available dates. The key may be invalid.")

    start, end = date(year, 1, 1), min(date.today(), date(year, 12, 31))
    for name, product in SENSORS.items():
        sp, nrt = avail.get(product + "_SP"), avail.get(product + "_NRT")
        plan = []                                   # (source, first day, last day)
        sp_last = min(sp[1], end) if sp else start - timedelta(days=1)
        if sp_last >= start:
            plan.append((product + "_SP", start, sp_last))
        if nrt:
            first = max(sp_last + timedelta(days=1), nrt[0], start)
            if first > sp_last + timedelta(days=1):
                print(f"  note: no {product} data between {sp_last} and {first}")
            if first <= min(nrt[1], end):
                plan.append((product + "_NRT", first, min(nrt[1], end)))

        kept = seen = 0
        path = os.path.join(out_dir, f"nrt_{name}_{year}_Argentina.csv")
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for source, d0, d1 in plan:
                day = d0
                while day <= d1:
                    n = min(5, (d1 - day).days + 1)
                    text = get(f"area/csv/{key}/{source}/{BBOX}/{n}/{day.isoformat()}")
                    if not text.lstrip().startswith("latitude"):
                        sys.exit(f"Unexpected answer from FIRMS for {source} {day}: {text.strip()[:120]}")
                    for r in csv.DictReader(io.StringIO(text)):
                        seen += 1
                        if border.contains(float(r["longitude"]), float(r["latitude"])):
                            r.setdefault("type", "0")
                            w.writerow(r)
                            kept += 1
                    print(f"  {source} {day} +{n}d  kept {kept:,} of {seen:,}", flush=True)
                    day += timedelta(days=n)
                    time.sleep(0.2)
        print(f"{name}: {kept:,} hotspots inside Argentina -> {path}")


if __name__ == "__main__":
    main()
