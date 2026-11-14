"""03_monthly.py — overpass-level table -> monthly table per 0.25 deg cell x satellite x day/night.
Run from project folder (repeat until it prints DONE): python3 harmonizare/scripts/03_monthly.py [budget_s] [--force]
*_sum  = plain monthly totals over all overpasses (type 0, confidence not low)
*_best = per local day keep only the strongest overpass, then sum over days (removes multi-overpass double counting)"""
import duckdb, os, shutil, glob, sys, time
budget = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1][0] != '-' else 140
force = '--force' in sys.argv; t0 = time.time()
con = duckdb.connect(); con.execute("SET memory_limit='1500MB'; SET threads=3; SET preserve_insertion_order=false; SET temp_directory='" + 'harmonizare/data/_ducktmp' + "'")
g = 'harmonizare/data/grid'; os.makedirs(f'{g}/monthly_parts', exist_ok=True)
bins = ['lt3','3_6','6_10','10_20','20_50','ge50']
add = ['n_sum','frp_sum','n_best','frp_best','nsub_best','days','ops','n_all','n0','n0_low','n_static','n_volc','n_offshore','scan_w','lst_w'] + [f'{p}_{b}' for b in bins for p in 'cf']
complete = True
for f in sorted(glob.glob(f'{g}/op_*.parquet')):
    dst = f'{g}/monthly_parts/m_' + os.path.basename(f)[3:]
    if os.path.exists(dst) and not force: continue
    if time.time() - t0 > budget: complete = False; print('budget reached; rerun'); break
    tmp = os.path.expanduser('~/tmp_m.parquet')
    con.execute(f"""COPY (
      WITH d AS (
        SELECT satellite, ix, iy, daynight, ldate,
               sum(n0q) AS n_sum, sum(frp0q) AS frp_sum, max(n0q) AS n_best, max(frp0q) AS frp_best, max(nsub0q) AS nsub_best,
               count(*) FILTER (n0q > 0) AS ops, sum(n_all) AS n_all, sum(n0) AS n0, sum(n0_low) AS n0_low,
               sum(n_static) AS n_static, sum(n_volc) AS n_volc, sum(n_offshore) AS n_offshore,
               sum(scan_mean * n0q) AS scan_w, sum(lst) AS lst_w, count(*) AS ops_all,
               {', '.join(f'sum(c_{b}) AS c_{b}, sum(f_{b}) AS f_{b}' for b in bins)}
        FROM '{f}' GROUP BY ALL)
      SELECT satellite, ix, iy, daynight, CAST(year(ldate) AS SMALLINT) AS year, CAST(month(ldate) AS TINYINT) AS month,
             sum(n_sum) AS n_sum, sum(frp_sum) AS frp_sum, sum(n_best) AS n_best, sum(frp_best) AS frp_best, sum(nsub_best) AS nsub_best,
             count(*) FILTER (n_sum > 0) AS days, sum(ops) AS ops, sum(n_all) AS n_all, sum(n0) AS n0, sum(n0_low) AS n0_low,
             sum(n_static) AS n_static, sum(n_volc) AS n_volc, sum(n_offshore) AS n_offshore,
             sum(scan_w) AS scan_w, sum(lst_w) AS lst_w, sum(ops_all) AS ops_all,
             {', '.join(f'sum(c_{b}) AS c_{b}, sum(f_{b}) AS f_{b}' for b in bins)}
      FROM d GROUP BY ALL) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    shutil.copyfile(tmp, dst); os.remove(tmp); print(os.path.basename(dst), round(time.time() - t0), 's', flush=True)
if complete:
    os.makedirs(f'{g}/monthly_025', exist_ok=True)
    for y in range(2000, 2027):
        dst = f'{g}/monthly_025/monthly_{y}.parquet'
        if os.path.exists(dst) and not force: continue
        con.execute(f"""COPY (
          SELECT satellite, ix, iy, daynight, year, month,
                 CAST(sum(n_sum) AS INT) AS n_sum, CAST(sum(frp_sum) AS FLOAT) AS frp_sum, CAST(sum(n_best) AS INT) AS n_best,
                 CAST(sum(frp_best) AS FLOAT) AS frp_best, CAST(sum(nsub_best) AS INT) AS nsub_best,
                 CAST(sum(days) AS SMALLINT) AS days, CAST(sum(ops) AS SMALLINT) AS ops,
                 CAST(sum(n_all) AS INT) AS n_all, CAST(sum(n0) AS INT) AS n0, CAST(sum(n0_low) AS INT) AS n0_low,
                 CAST(sum(n_static) AS INT) AS n_static, CAST(sum(n_volc) AS INT) AS n_volc, CAST(sum(n_offshore) AS INT) AS n_offshore,
                 CAST(sum(scan_w) / nullif(sum(n_sum), 0) AS FLOAT) AS scan_mean, CAST(sum(lst_w) / sum(ops_all) AS FLOAT) AS lst,
                 {', '.join(f'CAST(sum(c_{b}) AS INT) AS c_{b}, CAST(sum(f_{b}) AS FLOAT) AS f_{b}' for b in bins)}
          FROM read_parquet('{g}/monthly_parts/m_*.parquet') WHERE year = {y} GROUP BY ALL
        ) TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
        if con.execute(f"SELECT count(*) FROM '{dst}'").fetchone()[0] == 0: os.remove(dst)
    print(con.execute(f"SELECT satellite, count(*), sum(n_sum), min(year), max(year) FROM read_parquet('{g}/monthly_025/*.parquet') GROUP BY 1 ORDER BY 1").fetchall())
    print('DONE')
