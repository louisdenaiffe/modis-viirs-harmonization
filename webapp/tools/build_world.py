#!/usr/bin/env python3
"""Convert NASA FIRMS hotspot CSVs (any number of countries and years) into the files
the Fire Globe page reads. Needs numpy and pandas.

    python3 tools/build_world.py <folder with CSVs> <output folder> [coverage name]
        --modis-scale <folder of final_YYYY.parquet>  [--viirs-scale <table.parquet>]

The two conversion models of the team come in as tables on a 0.25 degree x month x day/night
grid (see "The two scales" below); reading them needs pyarrow.

Output layout (all little-endian binary, M = number of months since 2000-01):
  meta.json                 dates, month indexes, list of 10-degree blocks
  coarse.bin                per block and month: MODIS count, VIIRS count, VIIRS-scale value,
                            MODIS-scale value
  blocks/<lat>_<lon>.bin    per 1-degree tile in the block: cell split k and the same four
                            monthly series
  tiles/<lat>_<lon>.bin     the hotspots of one 1-degree tile, 9 bytes each, grouped into
                            k x k cells; when k > 1 the file starts with a cell directory
                            and per-cell monthly series (counts, and both scales as
                            round(64 * sqrt(value)) in 16 bits)
  factors/<lat>_<lon>.bin   per tile, the weight of one hotspot by 0.25 degree cell, month and
                            kind of hotspot: used for hotspots read one by one along a
                            selection's edge (n, then n sorted keys, then n weights)
  heat0/<month>.bin         world fire map, 0.25 degree cells, one file per month, both scales
  heat1/<lat>_<lon>.bin     detailed fire map, 0.05 degree cells, one file per block, both scales

The two scales. Every hotspot gets two weights, and everything the app shows is a sum of
weights, so any selection adds up exactly.

VIIRS scale ("what VIIRS would have counted"): a VIIRS hotspot weighs 1. A MODIS hotspot weighs 0
when VIIRS was flying, and otherwise (before February 2012, and on VIIRS outage days):
  - kept detections (type 0, confidence nominal or high): the --viirs-scale table gives the
    VIIRS-equivalent count of the cell, month and day/night (Louis's model, glm_cell on
    n_hotspots, made by scripts/export_app_table.py); it is shared equally between the kept
    MODIS hotspots there;
  - the other detections (low confidence, static sources), which that model leaves out, and any
    month the table does not cover: the VIIRS / MODIS ratio of the 1-degree tile and month of the
    year over the months both sensors cover, computed on the same kind of detections. Sparse
    tiles are pulled toward their 10-degree block's ratio, and blocks toward the global ratio
    (K pseudo-counts). A second ratio (VIIRS / Terra) is used before Aqua's first data in
    July 2002.

MODIS scale ("what MODIS Aqua would have counted"): the --modis-scale tables (Ianis's model,
harmonizare/APP_DATA/cells_monthly) give the Aqua-equivalent count n_eq of every cell, month and
day/night, and say which satellite it comes from: Terra (before July 2002), Aqua itself, or
VIIRS (from 2022). n_eq is shared equally between that satellite's hotspots there; the other
satellites weigh 0. For months after the last one in the tables, a VIIRS hotspot weighs the
tile's n_eq / VIIRS ratio for that month of the year and day/night, measured on the tables'
VIIRS-based months (same shrinkage); on VIIRS outage days Aqua hotspots count instead, as 1.

VIIRS outages: on days when the VIIRS satellite sent little or no data (for example
10-12 March 2026), the harmonized count of each affected 10-degree block uses that day's
MODIS hotspots with their VIIRS-scale weights, exactly as for the years before VIIRS. See
find_gaps() below. Raw MODIS and VIIRS counts are never changed.
"""
import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Pool

import numpy as np
import pandas as pd

AQUA_START = (2002 - 2000) * 12 + 6      # 2002-07
VIIRS_START = (2012 - 2000) * 12 + 1     # 2012-02, first full S-NPP month
K = 20.0                                 # shrinkage strength, in MODIS detections
KF = 100.0                               # same, in VIIRS detections (MODIS-scale fallback factors)
VH_START = (2022 - 2000) * 12            # first month the MODIS-scale tables are VIIRS-based
CELL_TARGET = 60000                      # aim for at most this many hotspots per cell
HEAT0, HEAT1 = 0.25, 0.05                # fire-map cell sizes in degrees
N0, N1 = 40, 200                         # cells per 10-degree block side at each size
EPOCH = np.datetime64("2000-01-01")

REC = np.dtype([("la", "i1"), ("lo", "<i2"), ("lat", "<u2"), ("lon", "<u2"),
                ("day", "<u2"), ("frp", "<u2"), ("fl", "u1")])              # 12 bytes, temporary
PT = np.dtype([("lat", "<u2"), ("lon", "<u2"), ("day", "<u2"), ("frp", "<u2"), ("fl", "u1")])  # 9 bytes
TILE = np.dtype([("la", "<i2"), ("lo", "<i2"), ("k", "<u2"), ("pad", "<u2"), ("n", "<u4")])  # 12 bytes
H0 = np.dtype([("x", "<u2"), ("y", "<u2"), ("v", "<f4"), ("w", "<f4")])     # v: VIIRS scale, w: MODIS scale
H1 = np.dtype([("x", "u1"), ("y", "u1"), ("v", "<u2"), ("w", "<u2")])
SRC_SAT = {"terra_backfill": 0, "aqua": 1, "viirs_harmonized": 2}           # MODIS-scale table sources
COLS = {"latitude", "longitude", "acq_date", "satellite", "confidence", "frp", "daynight", "type"}
SAT = {"Terra": 0, "T": 0, "Aqua": 1, "A": 1, "N": 2, "Suomi NPP": 2}
CONF = {"l": 0, "low": 0, "n": 1, "nominal": 1, "h": 2, "high": 2}


def parse_file(job):
    """Read one CSV and append its hotspots to per-block temporary files."""
    path, tmp = job
    try:
        df = pd.read_csv(path, usecols=lambda c: c in COLS, dtype=str)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError):
        return 0, 65535, 0, 0
    if not {"latitude", "longitude", "acq_date", "satellite"} <= set(df.columns) or df.empty:
        return 0, 65535, 0, 0
    lat = pd.to_numeric(df["latitude"], errors="coerce").to_numpy(float)
    lon = pd.to_numeric(df["longitude"], errors="coerce").to_numpy(float)
    sat = df["satellite"].str.strip().map(SAT).to_numpy(float)
    codes, dates = pd.factorize(df["acq_date"])
    days = (pd.to_datetime(pd.Series(dates), format="%Y-%m-%d", errors="coerce").to_numpy("datetime64[D]") - EPOCH).astype(float)
    day = np.where(codes >= 0, days[np.maximum(codes, 0)], np.nan)
    ok = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(sat) & np.isfinite(day) & (day >= 0) & (day < 65535)
    ok &= (lat >= -90) & (lat <= 90) & (lon >= -180) & (lon <= 180)
    if not ok.any():
        return 0, 65535, 0, 0
    conf_s = df["confidence"].str.strip().str.lower() if "confidence" in df else pd.Series("n", index=df.index)
    num = pd.to_numeric(conf_s, errors="coerce").to_numpy(float)
    conf = conf_s.map(CONF).to_numpy(float)
    conf = np.where(np.isfinite(conf), conf, np.where(num < 30, 0, np.where(num > 80, 2, 1)))
    typ = pd.to_numeric(df["type"], errors="coerce").fillna(0).to_numpy(int) & 3 if "type" in df else 0
    night = (df["daynight"].str.strip().str.upper() == "N").to_numpy(int) if "daynight" in df else 0
    frp = pd.to_numeric(df["frp"], errors="coerce").fillna(0).to_numpy(float) if "frp" in df else np.zeros(len(df))

    la = np.clip(np.floor(lat), -90, 89)
    lo = np.clip(np.floor(lon), -180, 179)
    rec = np.empty(len(df), REC)
    rec["la"], rec["lo"] = la, lo
    rec["lat"] = np.clip(np.rint((lat - la) * 65535), 0, 65535)
    rec["lon"] = np.clip(np.rint((lon - lo) * 65535), 0, 65535)
    rec["day"] = np.where(ok, day, 0)
    rec["frp"] = np.clip(np.rint(frp * 10), 0, 65535)
    rec["fl"] = np.where(ok, sat, 0).astype(int) | night << 2 | typ << 3 | conf.astype(int) << 5
    key = ((la // 10 + 9) * 36 + (lo // 10 + 18)).astype(int)
    rec, key, sat_ok = rec[ok], key[ok], sat[ok]
    order = np.argsort(key, kind="stable")
    rec, key = rec[order], key[order]
    cuts = np.flatnonzero(np.diff(key)) + 1
    pid = os.getpid()
    for seg, k0 in zip(np.split(rec, cuts), key[np.r_[0, cuts]]):
        with open(os.path.join(tmp, f"{k0}.{pid}.bin"), "ab") as fh:
            fh.write(seg.tobytes())
    viirs_days = rec["day"][(rec["fl"] & 3) == 2]
    return len(rec), int(rec["day"].min()), int(rec["day"].max()), int(viirs_days.max()) if len(viirs_days) else 0


def load_block(tmp, key):
    parts = [np.fromfile(os.path.join(tmp, f), REC) for f in os.listdir(tmp) if f.split(".")[0] == str(key)]
    return np.concatenate(parts) if len(parts) > 1 else parts[0]


def month_table(n_days):
    d = EPOCH + np.arange(n_days + 40)
    months = d.astype("datetime64[M]").astype(int) - (2000 - 1970) * 12
    return months.astype(np.int32)


def by_moy(a, lo, hi):
    """Sum columns lo..hi of a (..., M) array into 12 month-of-year columns."""
    out = np.zeros(a.shape[:-1] + (12,))
    for m in range(lo, hi + 1):
        out[..., m % 12] += a[..., m]
    return out


GAP_DAY = 0.5      # a day is an outage day when VIIRS/MODIS falls below half its usual value
GAP_BLOCK = 0.5    # ...and a block is filled that day when its VIIRS count is below half of
                   # what its MODIS count predicts
GAP_MIN_MODIS = 500  # ignore days with too few MODIS detections worldwide to judge


def find_gaps(daycounts, block_ratio, viirs_first_day, viirs_last_day):
    """Find (block, day) pairs where VIIRS data is missing.

    daycounts: {key: (D, 2) array of MODIS, VIIRS hotspots per day}
    block_ratio: {key: (12,) VIIRS/MODIS ratio of the block by month of year}
    Step 1, worldwide: each day's VIIRS/MODIS ratio is compared with the median of the
    15 days around it; a day far below (under GAP_DAY), or with no VIIRS at all while
    MODIS saw fires, is an outage day.
    Step 2, per block: on an outage day, a block whose VIIRS count is under GAP_BLOCK of
    what its MODIS count predicts is marked as missing (this catches partial outages,
    when only some orbits are lost).
    """
    D = next(iter(daycounts.values())).shape[0]
    tot = sum(daycounts.values())
    gm, gv = tot[:, 0].astype(float), tot[:, 1].astype(float)
    r = pd.Series(np.where(gm >= GAP_MIN_MODIS, gv / np.maximum(gm, 1), np.nan))
    # The usual ratio around each day ignores days with no VIIRS at all, so a long outage
    # (like 3-14 November 2026, when NASA published no Suomi NPP data) cannot hide itself.
    med = r.where(gv > 0).rolling(15, center=True, min_periods=5).median().to_numpy()
    days = np.arange(D)
    bad = (days >= viirs_first_day) & (days <= viirs_last_day) & (gm >= GAP_MIN_MODIS) & \
          ((r.to_numpy() < GAP_DAY * med) | (gv == 0))
    bad_days = np.flatnonzero(bad)
    moy = ((EPOCH + bad_days).astype("datetime64[M]").astype(int)) % 12
    gaps = {}
    for key, dc in daycounts.items():
        m, v = dc[bad_days, 0], dc[bad_days, 1]
        hit = (m > 0) & (v < GAP_BLOCK * block_ratio[key][moy] * m)
        if hit.any():
            gaps[key] = bad_days[hit]
    return bad_days, gaps


def kept_of(fl):
    """Detections the VIIRS-scale model is fitted on: type 0, confidence nominal or high."""
    return ((fl >> 3) & 3 == 0) & ((fl >> 5) & 3 >= 1)


def read_table(frames, val, M, src=None):
    """A model table (ix, iy, year, month, daynight, value) as arrays sorted by 10-degree block.
    d = position of the cell, month and day/night inside the block: ((cell * M) + month) * 2 + night."""
    import pandas as pd
    df = pd.concat(frames, ignore_index=True)
    m = (df["year"].to_numpy(np.int64) - 2000) * 12 + df["month"].to_numpy(np.int64) - 1
    ix, iy = df["ix"].to_numpy(np.int64), df["iy"].to_numpy(np.int64)
    ok = (m >= 0) & (m < M) & (ix >= 0) & (ix < 36 * N0) & (iy >= 0) & (iy < 18 * N0)
    night = (df["daynight"].astype(str).to_numpy() == "N").astype(np.int64)
    key = (iy // N0) * 36 + ix // N0
    d = (((iy % N0) * N0 + ix % N0) * M + m) * 2 + night
    s = df[src].map(SRC_SAT).fillna(-1).to_numpy(np.int8) if src else np.zeros(len(df), np.int8)
    o = np.flatnonzero(ok)
    o = o[np.argsort(key[o], kind="stable")]
    return {"key": key[o], "d": d[o], "v": df[val].to_numpy(np.float32)[o], "s": s[o],
            "first": int(m.min()), "last": int(m.max())}


def table_rows(tab, key):
    a, b = np.searchsorted(tab["key"], [key, key + 1])
    return slice(a, b)


def main():
    ap = argparse.ArgumentParser(usage="build_world.py <folder with CSVs> <output folder> [coverage name] "
                                       "--modis-scale <folder> [--viirs-scale <table.parquet>]")
    ap.add_argument("src"), ap.add_argument("out"), ap.add_argument("coverage", nargs="?", default="custom")
    ap.add_argument("--modis-scale", required=True, help="folder with Ianis's final_YYYY.parquet tables")
    ap.add_argument("--viirs-scale", help="table made by scripts/export_app_table.py")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    args = ap.parse_args()
    src, out, coverage = args.src, args.out, args.coverage
    tmp = os.path.join(out, "_tmp")
    for d in ("_tmp", "tiles", "blocks", "factors", "heat0", "heat1", "heat"):
        shutil.rmtree(os.path.join(out, d), ignore_errors=True)
    for d in ("_tmp", "tiles", "blocks", "factors", "heat0", "heat1"):
        os.makedirs(os.path.join(out, d))
    t0 = time.time()

    # ---- pass 1: read every CSV (in parallel) into per-block temporary files ----
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(src, followlinks=True) for f in fs if f.lower().endswith(".csv"))
    files.sort(key=os.path.getsize, reverse=True)
    total, dmin, dmax, vmax = 0, 65535, 0, 0
    with Pool(args.jobs) as pool:
        for i, (n, a, b, v) in enumerate(pool.imap_unordered(parse_file, [(f, tmp) for f in files], chunksize=4)):
            total += n
            dmin, dmax, vmax = min(dmin, a), max(dmax, b), max(vmax, v)
            if i % 500 == 0:
                print(f"read {i}/{len(files)} files, {total:,} hotspots, {time.time() - t0:.0f}s", flush=True)
    if not total:
        sys.exit("no usable rows found")
    print(f"pass 1 done: {total:,} hotspots in {time.time() - t0:.0f}s", flush=True)

    month_of = month_table(dmax + 2)
    M = int(month_of[dmax]) + 1
    full = lambda day: int(month_of[day]) if month_of[day + 1] != month_of[day] else int(month_of[day]) - 1
    # VIIRS counts are used up to the newest month with VIIRS data, even if that month is not
    # finished yet; the ratios only use months both sensors fully cover.
    viirs_end = int(month_of[vmax]) if vmax else -1
    overlap_end = min(full(vmax), full(dmax)) if vmax else -1
    keys = sorted({int(f.split(".")[0]) for f in os.listdir(tmp)})

    # ---- the two model tables ----
    import pandas as pd
    mfiles = sorted(f for f in os.listdir(args.modis_scale) if f.startswith("final_") and f.endswith(".parquet"))
    if not mfiles:
        sys.exit(f"no final_YYYY.parquet tables in {args.modis_scale}")
    cols = ["ix", "iy", "year", "month", "daynight", "n_eq", "source"]
    frames = [pd.read_parquet(os.path.join(args.modis_scale, f), columns=cols) for f in mfiles]
    TM = read_table([f[f["n_eq"] > 0] for f in frames], "n_eq", M, "source")
    del frames
    tab_end = min(TM["last"], M - 1)          # months after it use the fallback factors
    TV = None
    if args.viirs_scale:
        TV = read_table([pd.read_parquet(args.viirs_scale, columns=["ix", "iy", "year", "month", "daynight", "n_veq"])],
                        "n_veq", M)
    else:
        print("no --viirs-scale table: the VIIRS scale uses the tile ratios only", flush=True)
    print(f"tables read in {time.time() - t0:.0f}s: MODIS scale {len(TM['d']):,} rows (months {TM['first']}-{TM['last']})"
          + (f", VIIRS scale {len(TV['d']):,} rows (months {TV['first']}-{TV['last']})" if TV else ""), flush=True)

    # ---- pass 2a: monthly counts per tile and satellite, needed for the ratios ----
    counts, counts_r, daycounts, vh = {}, {}, {}, {}
    D = dmax + 1
    for key in keys:
        rec = load_block(tmp, key)
        bla, blo = (key // 36 - 9) * 10, (key % 36 - 18) * 10
        t = (rec["la"].astype(np.int64) - bla) * 10 + (rec["lo"].astype(np.int64) - blo)
        sat, mo = rec["fl"] & 3, month_of[rec["day"]].astype(np.int64)
        idx = (t * 3 + sat) * M + mo
        counts[key] = np.bincount(idx, minlength=100 * 3 * M).reshape(100, 3, M)
        # the same counts for the detections the VIIRS-scale model leaves out
        counts_r[key] = np.bincount(idx[~kept_of(rec["fl"])], minlength=100 * 3 * M).reshape(100, 3, M)
        daycounts[key] = np.bincount(rec["day"].astype(np.int64) * 2 + (sat == 2),
                                     minlength=2 * D).reshape(D, 2)
        # VIIRS hotspots by tile, day/night and month of year over the tables' VIIRS-based months
        v = (sat == 2) & (mo >= VH_START) & (mo <= tab_end)
        vh[key] = np.bincount((t[v] * 2 + (rec["fl"][v] >> 2 & 1)) * 12 + mo[v] % 12,
                              minlength=100 * 2 * 12).reshape(100, 2, 12)
    print(f"pass 2a done in {time.time() - t0:.0f}s", flush=True)

    def ratios(c):                       # c: (..., 3, M) -> VIIRS, MODIS, Terra sums by month of year
        return (by_moy(c[..., 2, :], VIIRS_START, overlap_end),
                by_moy(c[..., 0, :] + c[..., 1, :], VIIRS_START, overlap_end),
                by_moy(c[..., 0, :], VIIRS_START, overlap_end))
    safe = lambda a, b, alt: np.where(b > 0, a / np.maximum(b, 1), alt)

    def ratio_set(cnt):
        """Global ratios, and a function giving a block's tile ratios (VIIRS/MODIS, VIIRS/Terra)."""
        gv = gm = gt = 0
        for c in cnt.values():
            v, m, t_ = ratios(c.sum(0))
            gv, gm, gt = gv + v, gm + m, gt + t_
        g_rm = safe(gv, gm, gv.sum() / max(gm.sum(), 1))
        g_rt = safe(gv, gt, gv.sum() / max(gt.sum(), 1))

        def tiles(key):
            c = cnt[key]
            bv, bm, bt = ratios(c.sum(0))
            b_rm, b_rt = (bv + K * g_rm) / (bm + K), (bv + K * g_rt) / (bt + K)
            tv, tm, tt = ratios(c)
            return ((tv + K * b_rm) / (tm + K)).astype(np.float32), ((tv + K * b_rt) / (tt + K)).astype(np.float32), b_rm
        return g_rm, g_rt, tiles
    g_rm, g_rt, tiles_all = ratio_set(counts)        # every detection
    _, _, tiles_rest = ratio_set(counts_r)           # only those the VIIRS-scale model leaves out
    del counts_r

    # ---- MODIS scale after the tables' last month: n_eq / VIIRS per tile, month of year, day/night ----
    fb_num, g_num, g_den = {}, np.zeros((2, 12)), np.zeros((2, 12))
    for key in keys:
        r = table_rows(TM, key)
        d, v = TM["d"][r], TM["v"][r]
        mo = (d // 2) % M
        sel = (TM["s"][r] == 2) & (mo >= VH_START)
        d, v, mo = d[sel], v[sel], mo[sel]
        c16 = d // (2 * M)
        tl = (c16 // N0 // 4) * 10 + (c16 % N0) // 4
        fb_num[key] = np.bincount((tl * 2 + d % 2) * 12 + mo % 12, weights=v, minlength=2400).reshape(100, 2, 12)
        g_num += fb_num[key].sum(0)
        g_den += vh[key].sum(0)
    g_f = safe(g_num, g_den, g_num.sum() / max(g_den.sum(), 1))

    def fb_tiles(key):
        b = (fb_num[key].sum(0) + KF * g_f) / (vh[key].sum(0) + KF)
        return ((fb_num[key] + KF * b) / (vh[key] + KF)).astype(np.float32)      # (100, 2, 12)

    # ---- VIIRS outages: which blocks are missing VIIRS data on which days ----
    b_ratio = {key: tiles_all(key)[2] for key in keys}
    first_vday = int(np.argmax(month_of >= VIIRS_START))
    last_vday = int(np.flatnonzero(month_of <= viirs_end)[-1]) if viirs_end >= 0 else -1
    bad_days, gaps = find_gaps(daycounts, b_ratio, first_vday, last_vday)
    del daycounts
    gap_months = sorted({int(month_of[d]) for ds in gaps.values() for d in ds})
    print(f"VIIRS outages: {len(bad_days)} days, {sum(len(v) for v in gaps.values())} block-days filled with MODIS", flush=True)

    # ---- pass 2b: weights, tiles, block indexes and fire-map grids ----
    coarse, blocks_meta = [], []
    heat0 = [[] for _ in range(M)]
    in_v_month = (np.arange(M) >= VIIRS_START) & (np.arange(M) <= viirs_end)
    Y = (M + 11) // 12
    rep = {k: np.zeros(Y) for k in ("terra", "aqua", "viirs", "viirs_scale", "modis_scale", "table_v", "lost_v",
                                    "table_m", "lost_m", "modis_from_table", "modis_from_ratio")}
    size = N0 * N0 * M * 2
    enc = lambda cs: np.minimum(np.rint(64 * np.sqrt(cs)), 65535).astype("<u2").tobytes()
    for bi, key in enumerate(keys):
        bla, blo = (key // 36 - 9) * 10, (key % 36 - 18) * 10
        c = counts[key]
        r_m, r_t, _ = tiles_all(key)                                  # (100, 12)
        q_m, q_t, _ = tiles_rest(key)
        f_fb = fb_tiles(key)
        n_tile = c.sum((1, 2))
        k_tile = np.ones(100, np.uint32)
        for k in (2, 4, 8, 16):
            k_tile[n_tile / (k_tile ** 2) > CELL_TARGET] = k

        rec = load_block(tmp, key)
        t = ((rec["la"].astype(np.int32) - bla) * 10 + (rec["lo"].astype(np.int32) - blo)).astype(np.uint32)
        kk = k_tile[t]
        cell = ((rec["lat"].astype(np.uint32) * kk) >> 16) * kk + ((rec["lon"].astype(np.uint32) * kk) >> 16)
        order = np.argsort(t * 256 + cell, kind="stable")
        rec, t, cell = rec[order], t[order], cell[order]
        del order, kk
        m = month_of[rec["day"]].astype(np.int64)
        sat = (rec["fl"] & 3).astype(np.int64)
        night = (rec["fl"] >> 2 & 1).astype(np.int64)
        kept = kept_of(rec["fl"])
        is_mod = sat < 2
        moy = m % 12
        gapday, gapmonth = np.zeros(D + 1, bool), np.zeros(M, bool)
        if key in gaps:
            gapday[gaps[key]] = True
            gapmonth[month_of[gaps[key]]] = True
        gap = gapday[rec["day"]]
        era = in_v_month[m] & ~gap          # VIIRS-era months, except days VIIRS was missing here
        lonf = (rec["lo"].astype(np.float32) - blo) + rec["lon"] / np.float32(65535)
        latf = (rec["la"].astype(np.float32) - bla) + rec["lat"] / np.float32(65535)
        # 0.25 degree cell: quarter of the tile, from the stored 16-bit position (the app does the same)
        x4, y4 = (rec["lon"].astype(np.int64) * 4) >> 16, (rec["lat"].astype(np.int64) * 4) >> 16
        x0 = (rec["lo"].astype(np.int64) - blo) * 4 + x4
        y0 = (rec["la"].astype(np.int64) - bla) * 4 + y4
        d = ((y0 * N0 + x0) * M + m) * 2 + night          # 0.25 degree cell, month, day/night

        # VIIRS scale. pv = what a MODIS hotspot weighs when VIIRS is not there.
        ratio = np.where(m < AQUA_START, np.where(kept, r_t[t, moy], q_t[t, moy]), np.where(kept, r_m[t, moy], q_m[t, moy]))
        from_tab = np.zeros(len(rec), bool)
        pv = ratio
        if TV is not None:
            tv = np.full(size, np.nan, np.float32)
            r = table_rows(TV, key)
            tv[TV["d"][r]] = TV["v"][r]
            nk = np.bincount(d[is_mod & kept], minlength=size)
            from_tab = is_mod & kept & np.isfinite(tv[d])
            pv = np.where(from_tab, tv[d] / np.maximum(nk[d], 1), ratio)
            pre = (TV["d"][r] // 2) % M < VIIRS_START
            yr = ((TV["d"][r] // 2) % M // 12)[pre]
            rep["table_v"] += np.bincount(yr, weights=TV["v"][r][pre], minlength=Y)
            rep["lost_v"] += np.bincount(yr, weights=(TV["v"][r] * (nk[TV["d"][r]] == 0))[pre], minlength=Y)
            del tv, nk
        pv = np.where(is_mod, pv, 0)
        w = np.where(sat == 2, era, np.where(era, 0, pv)).astype(np.float32)

        # MODIS scale. wm0 = the weight before the outage-day rule of the months after the tables.
        tm_, ts = np.zeros(size, np.float32), np.full(size, -1, np.int8)
        r = table_rows(TM, key)
        tm_[TM["d"][r]], ts[TM["d"][r]] = TM["v"][r], TM["s"][r]
        ns = np.bincount(d * 3 + sat, minlength=size * 3)
        wm0 = np.where(ts[d] == sat, tm_[d] / np.maximum(ns[d * 3 + sat], 1), 0)
        late = m > tab_end
        wm0 = np.where(late, np.where(sat == 2, f_fb[t, night, moy], 0), wm0)
        wm = np.where(late & gap, sat == 1, wm0).astype(np.float32)
        yr = (TM["d"][r] // 2) % M // 12
        rep["table_m"] += np.bincount(yr, weights=TM["v"][r], minlength=Y)
        rep["lost_m"] += np.bincount(yr, weights=TM["v"][r] * (ns[TM["d"][r] * 3 + TM["s"][r]] == 0), minlength=Y)
        del tm_, ts, ns
        yr = m // 12
        for name, ww in (("terra", sat == 0), ("aqua", sat == 1), ("viirs", sat == 2), ("viirs_scale", w),
                         ("modis_scale", wm), ("modis_from_table", w * from_tab), ("modis_from_ratio", w * (is_mod & ~from_tab))):
            rep[name] += np.bincount(yr, weights=ww, minlength=Y)

        mod = c[:, 0, :] + c[:, 1, :]
        vii = c[:, 2, :]
        harm = np.bincount(t * M + m, weights=w, minlength=100 * M).reshape(100, M)
        harm_m = np.bincount(t * M + m, weights=wm, minlength=100 * M).reshape(100, M)
        # Weight of one hotspot by tile, 0.25 degree cell, month and kind, for hotspots the app
        # reads one by one along a selection's edge. Kinds 0-3: a MODIS hotspot on the VIIRS scale
        # when VIIRS is not there (kept * 2 + night); kinds 4-9: on the MODIS scale
        # (4 + satellite * 2 + night). Every hotspot of a kind in a cell and month weighs the same.
        fk = ((y4 * 4 + x4) * M + m) * 16
        sel_v = is_mod & (pv > 0) & (~in_v_month[m] | gapmonth[m])
        sel_m = wm0 > 0
        big = np.r_[(t[sel_v].astype(np.int64) << 32) + fk[sel_v] + kept[sel_v] * 2 + night[sel_v],
                    (t[sel_m].astype(np.int64) << 32) + fk[sel_m] + 4 + sat[sel_m] * 2 + night[sel_m]]
        big, first = np.unique(big, return_index=True)
        fval = np.r_[pv[sel_v], wm0[sel_m]][first].astype("<f4")
        fcut = np.searchsorted(big >> 32, np.arange(101))
        fkey = (big & 0xFFFFFFFF).astype("<u4")
        del big, first, sel_v, sel_m, fk
        present = np.flatnonzero(n_tile)
        bounds = np.searchsorted(t, np.r_[present, 100])
        trec = np.zeros(len(present), TILE)
        series = bytearray()
        for j, ti in enumerate(present):
            a, b = bounds[j], bounds[j] + n_tile[ti]
            la, lo, k = bla + ti // 10, blo + ti % 10, int(k_tile[ti])
            pts = np.empty(b - a, PT)
            for f in PT.names:
                pts[f] = rec[f][a:b]
            with open(os.path.join(out, "tiles", f"{la}_{lo}.bin"), "wb") as fh:
                if k > 1:
                    cc, mm, modis = cell[a:b], m[a:b], is_mod[a:b]
                    fh.write(np.r_[0, np.cumsum(np.bincount(cc, minlength=k * k))].astype("<u4").tobytes())
                    for sel in (modis, ~modis):
                        cs = np.bincount(cc[sel] * M + mm[sel], minlength=k * k * M)
                        fh.write(np.minimum(cs, 65535).astype("<u2").tobytes())
                    for ww in (w[a:b], wm[a:b]):   # both scales per cell and month, as round(64 * sqrt(value))
                        fh.write(enc(np.bincount(cc * M + mm, weights=ww, minlength=k * k * M)))
                fh.write(pts.tobytes())
            trec[j] = (la, lo, k, 0, n_tile[ti])
            series += (mod[ti].astype("<u4").tobytes() + vii[ti].astype("<u4").tobytes()
                       + harm[ti].astype("<f4").tobytes() + harm_m[ti].astype("<f4").tobytes())
            with open(os.path.join(out, "factors", f"{la}_{lo}.bin"), "wb") as fh:
                fa, fb = fcut[ti], fcut[ti + 1]
                fh.write(np.array([fb - fa], "<u4").tobytes() + fkey[fa:fb].tobytes() + fval[fa:fb].tobytes())
        with open(os.path.join(out, "blocks", f"{bla}_{blo}.bin"), "wb") as fh:
            fh.write(np.array([len(present)], "<u4").tobytes() + trec.tobytes() + bytes(series))
        coarse.append(mod.sum(0).astype("<u4").tobytes() + vii.sum(0).astype("<u4").tobytes()
                      + harm.sum(0).astype("<f4").tobytes() + harm_m.sum(0).astype("<f4").tobytes())
        blocks_meta.append([bla, blo])

        # fire-map grids, both scales
        keep = (w > 0) | (wm > 0)
        lonf, latf, mk, wk, wmk = lonf[keep], latf[keep], m[keep], w[keep], wm[keep]
        i0 = (mk * N0 + y0[keep]) * N0 + x0[keep]
        g0 = np.bincount(i0, weights=wk, minlength=M * N0 * N0).reshape(M, N0 * N0)
        g0m = np.bincount(i0, weights=wmk, minlength=M * N0 * N0).reshape(M, N0 * N0)
        for mi in np.flatnonzero(g0.any(1) | g0m.any(1)):
            nz = np.flatnonzero((g0[mi] > 0) | (g0m[mi] > 0))
            h = np.empty(len(nz), H0)
            h["x"] = nz % N0 + (blo + 180) * 4
            h["y"] = nz // N0 + (bla + 90) * 4
            h["v"], h["w"] = g0[mi, nz], g0m[mi, nz]
            heat0[mi].append(h)
        x1 = np.minimum((lonf / HEAT1).astype(np.int64), N1 - 1)
        y1 = np.minimum((latf / HEAT1).astype(np.int64), N1 - 1)
        i1 = (mk * N1 + y1) * N1 + x1
        g1 = np.bincount(i1, weights=wk, minlength=M * N1 * N1)
        g1m = np.bincount(i1, weights=wmk, minlength=M * N1 * N1)
        nz = np.flatnonzero((g1 > 0) | (g1m > 0))
        h = np.empty(len(nz), H1)
        cellidx = nz % (N1 * N1)
        h["x"], h["y"] = cellidx % N1, cellidx // N1
        for name, gg in (("v", g1[nz]), ("w", g1m[nz])):       # eighths of a hotspot; 0 only when there is none
            h[name] = np.where(gg > 0, np.clip(np.rint(gg * 8), 1, 65535), 0)
        offs = np.searchsorted(nz // (N1 * N1), np.arange(M + 1)).astype("<u4")
        with open(os.path.join(out, "heat1", f"{bla}_{blo}.bin"), "wb") as fh:
            fh.write(offs.tobytes() + h.tobytes())

        del rec, t, cell, m, sat, w, wm, wm0, pv, g0, g0m, g1, g1m, gap, d
        for f in os.listdir(tmp):
            if f.split(".")[0] == str(key):
                os.remove(os.path.join(tmp, f))
        if bi % 25 == 0:
            print(f"block {bi}/{len(keys)}, {time.time() - t0:.0f}s", flush=True)

    with open(os.path.join(out, "coarse.bin"), "wb") as fh:
        fh.write(b"".join(coarse))
    for mi, parts in enumerate(heat0):
        with open(os.path.join(out, "heat0", f"{mi}.bin"), "wb") as fh:
            if parts:
                fh.write(np.concatenate(parts).tobytes())
    shutil.rmtree(tmp, ignore_errors=True)
    for old in ("index.json", "countries.bin"):      # countries.bin must be recomputed (README, step 3)
        if os.path.exists(os.path.join(out, old)):
            os.remove(os.path.join(out, old))

    iso = lambda day: str(EPOCH + int(day))
    meta = {
        "version": 3, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage": coverage, "hotspots": int(total), "months": M,
        "firstDate": iso(dmin), "lastDate": iso(dmax),
        "aquaStart": AQUA_START, "viirsStart": VIIRS_START, "viirsEnd": viirs_end,
        "overlap": [VIIRS_START, overlap_end], "shrinkK": K,
        "heat0": HEAT0, "heat1": HEAT1,
        "global": {"rM": [round(float(x), 4) for x in g_rm], "rT": [round(float(x), 4) for x in g_rt]},
        "blocks": blocks_meta,
        # The model tables behind the two scales. Months after modisScale.last use the fallback
        # factors; from modisScale.viirsFrom the MODIS scale is converted VIIRS.
        "viirsScale": {"table": bool(TV), "last": TV["last"] if TV else -1},
        "modisScale": {"first": TM["first"], "last": tab_end, "viirsFrom": VH_START},
        # VIIRS outages filled with converted MODIS: per block, the days filled.
        "gapMonths": gap_months,
        "gapDays": [iso(d) for d in bad_days],
        "gaps": {f"{(k // 36 - 9) * 10}_{(k % 36 - 18) * 10}": [int(d) for d in v] for k, v in gaps.items()},
    }
    with open(os.path.join(out, "meta.json"), "w") as fh:
        json.dump(meta, fh, separators=(",", ":"))
    # Yearly world totals, to check the build (not read by the app).
    with open(os.path.join(out, "build_report.csv"), "w") as fh:
        fh.write("year," + ",".join(rep) + "\n")
        for y in range(Y):
            fh.write(f"{2000 + y}," + ",".join(f"{rep[k][y]:.0f}" for k in rep) + "\n")
    print(f"\n{total:,} hotspots, {len(keys)} blocks, {time.time() - t0:.0f}s")
    print(f"dates {meta['firstDate']} to {meta['lastDate']}; overlap months {VIIRS_START}-{overlap_end}")
    print("global VIIRS/MODIS ratio by month:", " ".join(f"{x:.2f}" for x in g_rm))
    tv, tm = rep["table_v"].sum(), rep["table_m"].sum()
    print(f"VIIRS-scale table before 2012: {tv:,.0f}, of which {rep['lost_v'].sum():,.0f} in cells where this build has no kept MODIS hotspot")
    print(f"MODIS-scale tables: {tm:,.0f}, of which {rep['lost_m'].sum():,.0f} in cells where this build has no hotspot of the source satellite")


if __name__ == "__main__":
    main()
