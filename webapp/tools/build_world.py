#!/usr/bin/env python3
"""Convert NASA FIRMS hotspot CSVs (any number of countries and years) into the files
the Fire Globe page reads. Needs numpy and pandas.

    python3 tools/build_world.py <folder with CSVs> <output folder> [coverage name]

Output layout (all little-endian binary, M = number of months since 2000-01):
  meta.json                 dates, month indexes, list of 10-degree blocks
  coarse.bin                per block: MODIS count, VIIRS count, harmonized count, per month
  blocks/<lat>_<lon>.bin    per 1-degree tile in the block: cell split k, ratios, monthly series
  tiles/<lat>_<lon>.bin     the hotspots of one 1-degree tile, 9 bytes each, grouped into
                            k x k cells; when k > 1 the file starts with a cell directory
                            and per-cell monthly counts
  heat0/<month>.bin         world fire map, 0.25 degree cells, one file per month
  heat1/<lat>_<lon>.bin     detailed fire map, 0.05 degree cells, one file per block

Harmonization: VIIRS is the reference. For every 1-degree tile and month of the year,
ratio = VIIRS / MODIS hotspots over the months both sensors cover. Sparse tiles are pulled
toward their 10-degree block's ratio, and blocks toward the global ratio (K pseudo-counts).
A second ratio (VIIRS / Terra) is used before Aqua's first data in July 2002.

VIIRS outages: on days when the VIIRS satellite sent little or no data (for example
10-12 March 2026), the harmonized count of each affected 10-degree block uses that day's
MODIS hotspots multiplied by the ratio, exactly as for the years before VIIRS. See
find_gaps() below. Raw MODIS and VIIRS counts are never changed.
"""
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
CELL_TARGET = 60000                      # aim for at most this many hotspots per cell
HEAT0, HEAT1 = 0.25, 0.05                # fire-map cell sizes in degrees
N0, N1 = 40, 200                         # cells per 10-degree block side at each size
EPOCH = np.datetime64("2000-01-01")

REC = np.dtype([("la", "i1"), ("lo", "<i2"), ("lat", "<u2"), ("lon", "<u2"),
                ("day", "<u2"), ("frp", "<u2"), ("fl", "u1")])              # 12 bytes, temporary
PT = np.dtype([("lat", "<u2"), ("lon", "<u2"), ("day", "<u2"), ("frp", "<u2"), ("fl", "u1")])  # 9 bytes
TILE = np.dtype([("la", "<i2"), ("lo", "<i2"), ("k", "<u2"), ("pad", "<u2"), ("n", "<u4"),
                 ("rM", "<f4", 12), ("rT", "<f4", 12)])                     # 108 bytes
H0 = np.dtype([("x", "<u2"), ("y", "<u2"), ("v", "<f4")])
H1 = np.dtype([("x", "u1"), ("y", "u1"), ("v", "<u2")])
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
    15 days around it; a day far below (under GAP_DAY) is an outage day.
    Step 2, per block: on an outage day, a block whose VIIRS count is under GAP_BLOCK of
    what its MODIS count predicts is marked as missing (this catches partial outages,
    when only some orbits are lost).
    """
    D = next(iter(daycounts.values())).shape[0]
    tot = sum(daycounts.values())
    gm, gv = tot[:, 0].astype(float), tot[:, 1].astype(float)
    r = pd.Series(np.where(gm >= GAP_MIN_MODIS, gv / np.maximum(gm, 1), np.nan))
    med = r.rolling(15, center=True, min_periods=5).median().to_numpy()
    days = np.arange(D)
    bad = (days >= viirs_first_day) & (days <= viirs_last_day) & (gm >= GAP_MIN_MODIS) & (r.to_numpy() < GAP_DAY * med)
    bad_days = np.flatnonzero(bad)
    moy = ((EPOCH + bad_days).astype("datetime64[M]").astype(int)) % 12
    gaps = {}
    for key, dc in daycounts.items():
        m, v = dc[bad_days, 0], dc[bad_days, 1]
        hit = (m > 0) & (v < GAP_BLOCK * block_ratio[key][moy] * m)
        if hit.any():
            gaps[key] = bad_days[hit]
    return bad_days, gaps


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, out = sys.argv[1], sys.argv[2]
    coverage = sys.argv[3] if len(sys.argv) > 3 else "custom"
    tmp = os.path.join(out, "_tmp")
    for d in ("_tmp", "tiles", "blocks", "heat0", "heat1", "heat"):
        shutil.rmtree(os.path.join(out, d), ignore_errors=True)
    for d in ("_tmp", "tiles", "blocks", "heat0", "heat1"):
        os.makedirs(os.path.join(out, d))
    t0 = time.time()

    # ---- pass 1: read every CSV (in parallel) into per-block temporary files ----
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(src) for f in fs if f.lower().endswith(".csv"))
    files.sort(key=os.path.getsize, reverse=True)
    total, dmin, dmax, vmax = 0, 65535, 0, 0
    with Pool(4) as pool:
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
    viirs_end = full(vmax) if vmax else -1
    overlap_end = min(viirs_end, full(dmax))
    keys = sorted({int(f.split(".")[0]) for f in os.listdir(tmp)})

    # ---- pass 2a: monthly counts per tile and satellite, needed for the ratios ----
    counts, daycounts = {}, {}
    D = dmax + 1
    for key in keys:
        rec = load_block(tmp, key)
        bla, blo = (key // 36 - 9) * 10, (key % 36 - 18) * 10
        t = (rec["la"].astype(np.int32) - bla) * 10 + (rec["lo"].astype(np.int32) - blo)
        idx = (t * 3 + (rec["fl"] & 3)) * M + month_of[rec["day"]]
        counts[key] = np.bincount(idx, minlength=100 * 3 * M).reshape(100, 3, M)
        daycounts[key] = np.bincount(rec["day"].astype(np.int64) * 2 + ((rec["fl"] & 3) == 2),
                                     minlength=2 * D).reshape(D, 2)
    print(f"pass 2a done in {time.time() - t0:.0f}s", flush=True)

    def ratios(c):                       # c: (..., 3, M) -> VIIRS, MODIS, Terra sums by month of year
        return (by_moy(c[..., 2, :], VIIRS_START, overlap_end),
                by_moy(c[..., 0, :] + c[..., 1, :], VIIRS_START, overlap_end),
                by_moy(c[..., 0, :], VIIRS_START, overlap_end))
    gv = gm = gt = 0
    for c in counts.values():
        v, m, t_ = ratios(c.sum(0))
        gv, gm, gt = gv + v, gm + m, gt + t_
    safe = lambda a, b, alt: np.where(b > 0, a / np.maximum(b, 1), alt)
    g_rm = safe(gv, gm, gv.sum() / max(gm.sum(), 1))
    g_rt = safe(gv, gt, gv.sum() / max(gt.sum(), 1))

    # ---- VIIRS outages: which blocks are missing VIIRS data on which days ----
    b_ratio = {}
    for key, c in counts.items():
        bv, bm, _ = ratios(c.sum(0))
        b_ratio[key] = (bv + K * g_rm) / (bm + K)
    first_vday = int(np.argmax(month_of >= VIIRS_START))
    last_vday = int(np.flatnonzero(month_of <= viirs_end)[-1]) if viirs_end >= 0 else -1
    bad_days, gaps = find_gaps(daycounts, b_ratio, first_vday, last_vday)
    del daycounts
    gap_months = sorted({int(month_of[d]) for ds in gaps.values() for d in ds})
    gi_of = np.full(M, -1, np.int64)
    gi_of[gap_months] = np.arange(len(gap_months))
    G = len(gap_months)
    print(f"VIIRS outages: {len(bad_days)} days, {sum(len(v) for v in gaps.values())} block-days filled with MODIS", flush=True)

    # ---- pass 2b: write tiles, block indexes and fire-map grids ----
    coarse, blocks_meta = [], []
    heat0 = [[] for _ in range(M)]
    in_v_month = (np.arange(M) >= VIIRS_START) & (np.arange(M) <= viirs_end)
    for bi, key in enumerate(keys):
        bla, blo = (key // 36 - 9) * 10, (key % 36 - 18) * 10
        c = counts[key]
        bv, bm, bt = ratios(c.sum(0))
        b_rm, b_rt = (bv + K * g_rm) / (bm + K), (bv + K * g_rt) / (bt + K)
        tv, tm, tt = ratios(c)
        r_m = ((tv + K * b_rm) / (tm + K)).astype(np.float32)        # (100, 12)
        r_t = ((tv + K * b_rt) / (tt + K)).astype(np.float32)
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
        m = month_of[rec["day"]]
        sat = rec["fl"] & 3
        moy = m % 12
        gapday = np.zeros(D + 1, bool)
        if key in gaps:
            gapday[gaps[key]] = True
        gap = gapday[rec["day"]]
        era = in_v_month[m] & ~gap          # VIIRS-era months, except days VIIRS was missing here
        w = np.where(sat == 2, era, np.where(era, 0, np.where(m < AQUA_START, r_t[t, moy], r_m[t, moy]))).astype(np.float32)

        mod = c[:, 0, :] + c[:, 1, :]
        vii = c[:, 2, :]
        harm = np.bincount(t * M + m, weights=w, minlength=100 * M).reshape(100, M)
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
                    cc, mm, is_mod = cell[a:b], m[a:b], sat[a:b] < 2
                    fh.write(np.r_[0, np.cumsum(np.bincount(cc, minlength=k * k))].astype("<u4").tobytes())
                    for sel in (is_mod, ~is_mod):
                        cs = np.bincount(cc[sel] * M + mm[sel], minlength=k * k * M)
                        fh.write(np.minimum(cs, 65535).astype("<u2").tobytes())
                    if G:   # per cell and outage month: VIIRS, then MODIS hotspots on outage days
                        gg = gap[a:b] & (gi_of[mm] >= 0)
                        for sel in (gg & ~is_mod, gg & is_mod):
                            cs = np.bincount(cc[sel] * G + gi_of[mm[sel]], minlength=k * k * G)
                            fh.write(np.minimum(cs, 65535).astype("<u2").tobytes())
                fh.write(pts.tobytes())
            trec[j] = (la, lo, k, 0, n_tile[ti], r_m[ti], r_t[ti])
            series += mod[ti].astype("<u4").tobytes() + vii[ti].astype("<u4").tobytes() + harm[ti].astype("<f4").tobytes()
        with open(os.path.join(out, "blocks", f"{bla}_{blo}.bin"), "wb") as fh:
            fh.write(np.array([len(present)], "<u4").tobytes() + trec.tobytes() + bytes(series))
        coarse.append(mod.sum(0).astype("<u4").tobytes() + vii.sum(0).astype("<u4").tobytes() + harm.sum(0).astype("<f4").tobytes())
        blocks_meta.append([bla, blo])

        # fire-map grids (harmonized counts)
        lonf = (rec["lo"].astype(np.float32) - blo) + rec["lon"] / np.float32(65535)
        latf = (rec["la"].astype(np.float32) - bla) + rec["lat"] / np.float32(65535)
        keep = w > 0
        lonf, latf, mk, wk = lonf[keep], latf[keep], m[keep].astype(np.int64), w[keep]
        x0 = np.minimum((lonf / HEAT0).astype(np.int64), N0 - 1)
        y0 = np.minimum((latf / HEAT0).astype(np.int64), N0 - 1)
        g0 = np.bincount((mk * N0 + y0) * N0 + x0, weights=wk, minlength=M * N0 * N0).reshape(M, N0 * N0)
        for mi in np.flatnonzero(g0.any(1)):
            nz = np.flatnonzero(g0[mi])
            h = np.empty(len(nz), H0)
            h["x"] = nz % N0 + (blo + 180) * 4
            h["y"] = nz // N0 + (bla + 90) * 4
            h["v"] = g0[mi, nz]
            heat0[mi].append(h)
        x1 = np.minimum((lonf / HEAT1).astype(np.int64), N1 - 1)
        y1 = np.minimum((latf / HEAT1).astype(np.int64), N1 - 1)
        g1 = np.bincount((mk * N1 + y1) * N1 + x1, weights=wk, minlength=M * N1 * N1)
        nz = np.flatnonzero(g1)
        h = np.empty(len(nz), H1)
        cellidx = nz % (N1 * N1)
        h["x"], h["y"] = cellidx % N1, cellidx // N1
        h["v"] = np.clip(np.rint(g1[nz] * 8), 1, 65535)
        offs = np.searchsorted(nz // (N1 * N1), np.arange(M + 1)).astype("<u4")
        with open(os.path.join(out, "heat1", f"{bla}_{blo}.bin"), "wb") as fh:
            fh.write(offs.tobytes() + h.tobytes())

        del rec, t, cell, m, sat, w, g0, g1, gap
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
    for old in ("index.json",):
        if os.path.exists(os.path.join(out, old)):
            os.remove(os.path.join(out, old))

    iso = lambda day: str(EPOCH + int(day))
    meta = {
        "version": 2, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage": coverage, "hotspots": int(total), "months": M,
        "firstDate": iso(dmin), "lastDate": iso(dmax),
        "aquaStart": AQUA_START, "viirsStart": VIIRS_START, "viirsEnd": viirs_end,
        "overlap": [VIIRS_START, overlap_end], "shrinkK": K,
        "heat0": HEAT0, "heat1": HEAT1,
        "global": {"rM": [round(float(x), 4) for x in g_rm], "rT": [round(float(x), 4) for x in g_rt]},
        "blocks": blocks_meta,
        # VIIRS outages filled with converted MODIS: the months concerned (tile files carry
        # extra per-cell counts for these) and, per block, the days filled.
        "gapMonths": gap_months,
        "gapDays": [iso(d) for d in bad_days],
        "gaps": {f"{(k // 36 - 9) * 10}_{(k % 36 - 18) * 10}": [int(d) for d in v] for k, v in gaps.items()},
    }
    with open(os.path.join(out, "meta.json"), "w") as fh:
        json.dump(meta, fh, separators=(",", ":"))
    print(f"\n{total:,} hotspots, {len(keys)} blocks, {time.time() - t0:.0f}s")
    print(f"dates {meta['firstDate']} to {meta['lastDate']}; overlap months {VIIRS_START}-{overlap_end}")
    print("global VIIRS/MODIS ratio by month:", " ".join(f"{x:.2f}" for x in g_rm))


if __name__ == "__main__":
    main()
