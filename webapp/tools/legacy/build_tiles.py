#!/usr/bin/env python3
"""Convert NASA FIRMS hotspot CSVs into the files the Fire Globe page reads.

    python3 -I tools/build_tiles.py <folder with CSVs> <output folder> [coverage name]

Input : any number of FIRMS archive CSVs (MODIS and VIIRS S-NPP), found recursively.
Output: <out>/tiles/<lat>_<lon>.bin  one compact binary file per 1x1 degree square
        <out>/index.json             monthly totals per square + harmonization ratios

Harmonization (computed here, applied in the browser):
  VIIRS is the reference. For every 1-degree square and every month of the year we
  measure, over the years when both sensors flew, the ratio
        VIIRS hotspots / MODIS hotspots
  and use it to convert MODIS counts into "VIIRS-equivalent" counts. Squares with few
  detections are pulled toward the national ratio (K pseudo-detections) so a handful
  of points cannot produce a wild ratio. A second ratio (VIIRS / Terra only) covers
  2000 to mid-2002, when Aqua had not been launched yet.
"""
import csv
import json
import math
import os
import sys
from array import array
from datetime import date, datetime, timezone

ORIGIN = date(2000, 1, 1)
AQUA_START = (2002 - 2000) * 12 + 6      # month index of 2002-07, first Aqua data
VIIRS_START = (2012 - 2000) * 12 + 1     # month index of 2012-02, first full S-NPP month
K = 20.0                                 # shrinkage strength, in MODIS detections
HEAT_CELL = 0.05                         # fire-map cell size in degrees (about 5 km)
SAT = {"Terra": 0, "Aqua": 1, "N": 2,    # S-NPP is "N" in FIRMS files
       "T": 0, "A": 1, "Suomi NPP": 2}   # spellings used by the near-real-time API


def conf_class(value):
    """Low / nominal / high as 0 / 1 / 2. MODIS gives 0-100, VIIRS gives l/n/h."""
    v = value.strip().lower()
    if v in ("l", "low"):
        return 0
    if v in ("n", "nominal"):
        return 1
    if v in ("h", "high"):
        return 2
    try:
        n = float(v)
    except ValueError:
        return 1
    return 0 if n < 30 else (2 if n > 80 else 1)


class Tile:
    __slots__ = ("frp", "lat", "lon", "day", "time", "flags")

    def __init__(self):
        self.frp = array("f")
        self.lat = array("H")
        self.lon = array("H")
        self.day = array("H")
        self.time = array("H")
        self.flags = array("B")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, out = sys.argv[1], sys.argv[2]
    coverage = sys.argv[3] if len(sys.argv) > 3 else "custom"
    os.makedirs(os.path.join(out, "tiles"), exist_ok=True)

    tiles = {}
    rows = skipped = 0
    min_day, max_day = 10 ** 9, -1
    last_day = {0: -1, 1: -1, 2: -1}

    files = sorted(
        os.path.join(d, f) for d, _, fs in os.walk(src) for f in fs if f.lower().endswith(".csv")
    )
    for path in files:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                try:
                    sat = SAT.get(r["satellite"].strip())
                    if sat is None:          # NOAA-20/21 etc. are not used yet
                        skipped += 1
                        continue
                    lat, lon = float(r["latitude"]), float(r["longitude"])
                    y, m, d = r["acq_date"].split("-")
                    day = (date(int(y), int(m), int(d)) - ORIGIN).days
                    la, lo = math.floor(lat), math.floor(lon)
                    t = tiles.get((la, lo))
                    if t is None:
                        t = tiles[(la, lo)] = Tile()
                    t.frp.append(float(r["frp"] or 0))
                    t.lat.append(min(65535, round((lat - la) * 65535)))
                    t.lon.append(min(65535, round((lon - lo) * 65535)))
                    t.day.append(day)
                    t.time.append(int(r["acq_time"] or 0))
                    typ = int(r.get("type") or 0) & 3
                    night = 1 if r["daynight"].strip().upper() == "N" else 0
                    t.flags.append(sat | night << 2 | typ << 3 | conf_class(r["confidence"]) << 5)
                    rows += 1
                    min_day, max_day = min(min_day, day), max(max_day, day)
                    last_day[sat] = max(last_day[sat], day)
                except (KeyError, ValueError):
                    skipped += 1
        print(f"read {os.path.basename(path)}  total {rows:,}", flush=True)

    if not rows:
        sys.exit("no usable rows found")

    def month_of(day):
        d = date.fromordinal(ORIGIN.toordinal() + day)
        return (d.year - 2000) * 12 + d.month - 1

    n_months = month_of(max_day) + 1
    def last_full_month(day):
        """Last month completely covered by data that ends on this day."""
        m = month_of(day)
        return m if month_of(day + 1) != m else m - 1

    # A month that VIIRS only partly covers is not used as VIIRS: the app falls back to
    # scaled MODIS for it, and it is left out of the ratio calculation.
    viirs_end = last_full_month(last_day[2]) if last_day[2] >= 0 else -1
    modis_end = last_full_month(max(last_day[0], last_day[1]))
    overlap_end = min(viirs_end, modis_end)

    # Monthly totals per tile, per satellite; and write the binary tiles sorted by date.
    series = {}
    month_cache = {}
    for (la, lo), t in tiles.items():
        order = sorted(range(len(t.day)), key=t.day.__getitem__)
        cols = [array(c.typecode, (c[i] for i in order)) for c in (t.frp, t.lat, t.lon, t.day, t.time, t.flags)]
        if sys.byteorder == "big":
            for c in cols:
                c.byteswap()
        with open(os.path.join(out, "tiles", f"{la}_{lo}.bin"), "wb") as fh:
            n = array("I", [len(order)])
            if sys.byteorder == "big":
                n.byteswap()
            fh.write(n.tobytes())
            for c in cols:
                fh.write(c.tobytes())
        s = [[0] * n_months for _ in range(3)]
        for day, fl in zip(t.day, t.flags):
            m = month_cache.get(day)
            if m is None:
                m = month_cache[day] = month_of(day)
            s[fl & 3][m] += 1
        series[(la, lo)] = s

    # Ratios over the overlap period, per month of the year.
    def overlap_sums(s):
        v, mod, ter = [0] * 12, [0] * 12, [0] * 12
        for m in range(VIIRS_START, overlap_end + 1):
            moy = m % 12
            v[moy] += s[2][m]
            mod[moy] += s[0][m] + s[1][m]
            ter[moy] += s[0][m]
        return v, mod, ter

    gv, gm, gt = [0] * 12, [0] * 12, [0] * 12
    per_tile = {}
    for key, s in series.items():
        per_tile[key] = overlap_sums(s)
        for i in range(12):
            gv[i] += per_tile[key][0][i]
            gm[i] += per_tile[key][1][i]
            gt[i] += per_tile[key][2][i]
    all_v, all_m, all_t = sum(gv), sum(gm), sum(gt)
    g_rm = [(gv[i] / gm[i]) if gm[i] else (all_v / all_m if all_m else 1.0) for i in range(12)]
    g_rt = [(gv[i] / gt[i]) if gt[i] else (all_v / all_t if all_t else 1.0) for i in range(12)]

    index_tiles = {}
    for (la, lo), s in series.items():
        v, mod, ter = per_tile[(la, lo)]
        index_tiles[f"{la}_{lo}"] = {
            "n": len(tiles[(la, lo)].day),
            "T": s[0], "A": s[1], "V": s[2],
            "rM": [round((v[i] + K * g_rm[i]) / (mod[i] + K), 4) for i in range(12)],
            "rT": [round((v[i] + K * g_rt[i]) / (ter[i] + K), 4) for i in range(12)],
        }

    # Fire map: for every month, the harmonized hotspot count in each 0.05 degree cell
    # (about 5 km). One file per year: 12 counts, then cell x, cell y and value columns.
    heat = {}
    for (la, lo), t in tiles.items():
        meta = index_tiles[f"{la}_{lo}"]
        r_m, r_t = meta["rM"], meta["rT"]
        for day, fl, u_lat, u_lon in zip(t.day, t.flags, t.lat, t.lon):
            m = month_cache[day]
            in_viirs = VIIRS_START <= m <= viirs_end
            if fl & 3 == 2:
                if not in_viirs:
                    continue
                w = 1.0
            else:
                if in_viirs:
                    continue
                w = (r_t if m < AQUA_START else r_m)[m % 12]
            cell = (m % 12, int((lo + u_lon / 65535 + 180) / HEAT_CELL), int((la + u_lat / 65535 + 90) / HEAT_CELL))
            year_cells = heat.setdefault(m // 12, {})
            year_cells[cell] = year_cells.get(cell, 0.0) + w
    os.makedirs(os.path.join(out, "heat"), exist_ok=True)
    for y, cells in heat.items():
        counts, xs, ys, vs = array("I", [0] * 12), array("H"), array("H"), array("f")
        for (moy, cx, cy), w in sorted(cells.items()):
            counts[moy] += 1
            xs.append(cx)
            ys.append(cy)
            vs.append(w)
        cols = [counts, xs, ys, vs]
        if sys.byteorder == "big":
            for c in cols:
                c.byteswap()
        with open(os.path.join(out, "heat", f"{2000 + y}.bin"), "wb") as fh:
            for c in cols:
                fh.write(c.tobytes())

    iso = lambda day: date.fromordinal(ORIGIN.toordinal() + day).isoformat()
    index = {
        "version": 1,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage": coverage,
        "hotspots": rows,
        "months": n_months,
        "firstDate": iso(min_day),
        "lastDate": iso(max_day),
        "aquaStart": AQUA_START,
        "viirsStart": VIIRS_START,
        "viirsEnd": viirs_end,
        "overlap": [VIIRS_START, overlap_end],
        "shrinkK": K,
        "heatCell": HEAT_CELL,
        "global": {"rM": [round(x, 4) for x in g_rm], "rT": [round(x, 4) for x in g_rt]},
        "tiles": index_tiles,
    }
    with open(os.path.join(out, "index.json"), "w") as fh:
        json.dump(index, fh, separators=(",", ":"))

    print(f"\n{rows:,} hotspots in {len(tiles)} tiles ({skipped:,} rows skipped)")
    print(f"dates {index['firstDate']} to {index['lastDate']}; overlap months {VIIRS_START}-{overlap_end}")
    print("national VIIRS/MODIS ratio by month:", " ".join(f"{x:.2f}" for x in g_rm))
    print("national VIIRS/Terra ratio by month:", " ".join(f"{x:.2f}" for x in g_rt))


if __name__ == "__main__":
    main()
