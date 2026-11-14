"""02_grid.py — points Parquet -> overpass-level aggregates on the 0.25 deg grid.
Run from project folder: python3 harmonizare/scripts/02_grid.py [time_budget_s] [--force]
One row = one satellite overpass over one 0.25 deg cell (detections of the same satellite in the
same cell separated by <=20 min belong to the same overpass). Skips years already done.
If harmonizare/data/grid/static_mask_001.parquet (columns sx, sy) exists, those 0.01 deg cells are removed
from the *0/*0q columns' inputs (flag column masked=1 rows are dropped before aggregation)."""
import duckdb, glob, os, sys, time, shutil
budget = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1][0] != '-' else 150
force = '--force' in sys.argv
t0 = time.time()
os.makedirs('harmonizare/data/_ducktmp', exist_ok=True)
con = duckdb.connect(); con.execute(f"SET memory_limit='1500MB'; SET threads=3; SET preserve_insertion_order=false; SET temp_directory='harmonizare/data/_ducktmp'")
src, out = 'harmonizare/data/points', 'harmonizare/data/grid'
mask = f'{out}/static_mask_001.parquet'
anti = f"ANTI JOIN '{mask}' k ON (p.sx = k.sx AND p.sy = k.sy)" if os.path.exists(mask) else ''
print('static mask:', 'ON' if anti else 'off')
bins = [('lt3','frp < 3'), ('3_6','frp >= 3 AND frp < 6'), ('6_10','frp >= 6 AND frp < 10'), ('10_20','frp >= 10 AND frp < 20'), ('20_50','frp >= 20 AND frp < 50'), ('ge50','frp >= 50')]
q = "type = 0 AND conf_class <> 'l'"
binsql = ',\n'.join(f"count(*) FILTER ({q} AND {c}) AS c_{n}, CAST(coalesce(sum(frp) FILTER ({q} AND {c}),0) AS FLOAT) AS f_{n}" for n, c in bins)
for f in sorted(glob.glob(f'{src}/*.parquet'), key=lambda s: s.split('_')[-1]):
    name = os.path.basename(f); dst = f'{out}/op_{name}'
    if os.path.exists(dst) and not force: continue
    if time.time() - t0 > budget: print('budget reached; rerun to continue'); break
    t = time.time(); tmp = os.path.expanduser(f'~/tmp_op_{name}')
    for t_ in ('p0', 'am', 'sm'): con.execute(f"DROP TABLE IF EXISTS {t_}")
    # 1) detections outside masked 0.01-deg cells
    con.execute(f"""CREATE TEMP TABLE p0 AS SELECT p.sensor, p.satellite, p.ix, p.iy, p.ts, p.daynight, p.lst, p.frp, p.scan, p.type, p.conf_class, p.sx, p.sy
                    FROM '{f}' p {anti}""")
    print("  p0", round(time.time()-t), flush=True)
    # 2) aggregate to (satellite, cell, minute) -- no big join needed afterwards
    binmin = ', '.join(f"count(*) FILTER ({q} AND {c}) AS c_{n_}, coalesce(sum(frp) FILTER ({q} AND {c}), 0) AS f_{n_}" for n_, c in bins)
    con.execute(f"""CREATE TEMP TABLE am AS
      SELECT any_value(sensor) AS sensor, satellite, ix, iy, ts, min(daynight) AS daynight, sum(lst) AS lst_s,
             count(*) AS n_all, sum(frp) AS frp_all,
             count(*) FILTER (type = 0) AS n0, coalesce(sum(frp) FILTER (type = 0), 0) AS frp0,
             count(*) FILTER ({q}) AS n0q, coalesce(sum(frp) FILTER ({q}), 0) AS frp0q,
             count(*) FILTER (type = 1) AS n_volc, count(*) FILTER (type = 2) AS n_static, count(*) FILTER (type = 3) AS n_offshore,
             count(*) FILTER (type = 0 AND conf_class = 'l') AS n0_low, count(*) FILTER (type = 0 AND conf_class = 'h') AS n0_high,
             coalesce(sum(scan) FILTER ({q}), 0) AS scan_s, max(scan) FILTER ({q}) AS scan_max, max(frp) FILTER ({q}) AS frp_max, {binmin}
      FROM p0 GROUP BY satellite, ix, iy, ts""")
    print("  am", round(time.time()-t), flush=True)
    con.execute(f"""CREATE TEMP TABLE sm AS SELECT satellite, ix, iy, ts, count(*) AS nsub FROM
                    (SELECT DISTINCT satellite, ix, iy, ts, sx, sy FROM p0 WHERE {q}) GROUP BY ALL""")
    print("  sm", round(time.time()-t), flush=True)
    binop = ', '.join(f"sum(c_{n_}) AS c_{n_}, CAST(sum(f_{n_}) AS FLOAT) AS f_{n_}" for n_, c in bins)
    # 3) minutes <= 20 min apart in the same cell = one overpass; aggregate minutes to overpasses
    con.execute(f"""
    COPY (
      WITH j AS (SELECT am.*, coalesce(sm.nsub, 0) AS nsub FROM am LEFT JOIN sm USING (satellite, ix, iy, ts)),
      g AS (SELECT *, date_diff('minute', lag(ts) OVER (PARTITION BY satellite, ix, iy ORDER BY ts), ts) AS gap FROM j),
      o AS (SELECT *, sum(CASE WHEN gap IS NULL OR gap > 20 THEN 1 ELSE 0 END) OVER (PARTITION BY satellite, ix, iy ORDER BY ts) AS op FROM g)
      SELECT any_value(sensor) AS sensor, satellite, ix, iy,
             min(ts) AS t_start,
             CAST(min(ts) + to_minutes(CAST(round(((ix + 0.5) * 0.25 - 180) * 4) AS INT)) AS DATE) AS ldate,
             min(daynight) AS daynight, CAST(sum(lst_s) / sum(n_all) AS FLOAT) AS lst,
             sum(n_all) AS n_all, CAST(sum(frp_all) AS FLOAT) AS frp_all, sum(n0) AS n0, CAST(sum(frp0) AS FLOAT) AS frp0,
             sum(n0q) AS n0q, CAST(sum(frp0q) AS FLOAT) AS frp0q,
             sum(n_volc) AS n_volc, sum(n_static) AS n_static, sum(n_offshore) AS n_offshore, sum(n0_low) AS n0_low, sum(n0_high) AS n0_high,
             CAST(sum(scan_s) / nullif(sum(n0q), 0) AS FLOAT) AS scan_mean, CAST(max(scan_max) AS FLOAT) AS scan_max, CAST(max(frp_max) AS FLOAT) AS frp_max,
             {binop},
             sum(nsub) AS nsub0q   -- distinct sub-cells per minute, summed over the overpass (slight over-count if a sub-cell repeats)
      FROM o GROUP BY satellite, ix, iy, op
    ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    n = con.execute(f"SELECT count(*) FROM '{tmp}'").fetchone()[0]
    shutil.copyfile(tmp, dst); os.remove(tmp)
    print(f'{name}: {n:,} overpass-cells, {os.path.getsize(dst)/1e6:.0f} MB, {time.time()-t:.0f}s', flush=True)
print('done pass', round(time.time()-t0), 's')
