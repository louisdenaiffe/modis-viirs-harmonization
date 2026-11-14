"""06_apply_mask.py — remove static sources (flares, industry, volcano lava) from the monthly table.
Run from project folder, repeat until DONE:  python3 harmonizare/scripts/06_apply_mask.py [budget_s]
Needs data/points/*.parquet for all years (01_ingest.py) and data/grid/monthly_025_nomask/ (the unmasked monthly table).
Step 1: per sensor-year, sum the detections that fall in masked 0.01-deg cells (rezultate/static_mask/static_mask_001.parquet)
        per 0.25-deg cell x month x day/night x satellite  -> data/grid/mask_removed/removed_*.parquet (small)
Step 2: monthly_025 = monthly_025_nomask - removed (counts, FRP, FRP-class bins); n_best/frp_best/nsub_best are scaled by the
        same ratio as n_sum/frp_sum (approximation); cells emptied by the mask are dropped."""
import duckdb, glob, os, sys, time
budget = float(sys.argv[1]) if len(sys.argv) > 1 else 80; t0 = time.time()
G = 'harmonizare/data/grid'; MASK = 'harmonizare/rezultate/static_mask/static_mask_001.parquet'
os.makedirs(f'{G}/mask_removed', exist_ok=True); os.makedirs(f'{G}/monthly_025', exist_ok=True)
con = duckdb.connect(); con.execute("SET memory_limit='1200MB'; SET threads=3; SET preserve_insertion_order=false; SET temp_directory='harmonizare/data/_ducktmp'")
bins = [('lt3','frp < 3'), ('3_6','frp >= 3 AND frp < 6'), ('6_10','frp >= 6 AND frp < 10'), ('10_20','frp >= 10 AND frp < 20'), ('20_50','frp >= 20 AND frp < 50'), ('ge50','frp >= 50')]
q = "type = 0 AND conf_class <> 'l'"
binsql = ', '.join(f"count(*) FILTER ({q} AND {c}) AS c_{n}, coalesce(sum(frp) FILTER ({q} AND {c}), 0) AS f_{n}" for n, c in bins)
done = True
for f in sorted(glob.glob('harmonizare/data/points/*.parquet')):
    dst = f'{G}/mask_removed/removed_' + os.path.basename(f)
    if os.path.exists(dst): continue
    if time.time() - t0 > budget: done = False; print('budget reached; rerun'); break
    con.execute(f"""COPY (
      WITH p AS (SELECT p.*, CAST(ts + to_minutes(CAST(round(((ix + 0.5) * 0.25 - 180) * 4) AS INT)) AS DATE) AS ld
                 FROM '{f}' p SEMI JOIN '{MASK}' k ON (p.sx = k.sx AND p.sy = k.sy))
      SELECT satellite, ix, iy, daynight, CAST(year(ld) AS SMALLINT) AS year, CAST(month(ld) AS TINYINT) AS month,
             count(*) AS r_n_all, count(*) FILTER (type = 0) AS r_n0, count(*) FILTER (type = 0 AND conf_class = 'l') AS r_n0_low,
             count(*) FILTER ({q}) AS r_n, coalesce(sum(frp) FILTER ({q}), 0) AS r_frp, {binsql.replace(' AS c_', ' AS r_c_').replace(' AS f_', ' AS r_f_')}
      FROM p GROUP BY ALL) TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    print(os.path.basename(dst), con.execute(f"SELECT sum(r_n), round(sum(r_frp)) FROM '{dst}'").fetchone(), round(time.time() - t0), 's', flush=True)
if done:
    B = [b for b, _ in bins]
    sub = ', '.join([f"greatest(m.c_{b} - coalesce(r.r_c_{b}, 0), 0) AS c_{b}, greatest(m.f_{b} - coalesce(r.r_f_{b}, 0), 0) AS f_{b}" for b in B])
    for f in sorted(glob.glob(f'{G}/monthly_025_nomask/monthly_*.parquet')):
        dst = f'{G}/monthly_025/' + os.path.basename(f); y = int(os.path.basename(f)[8:12])
        con.execute(f"""COPY (
          WITH r AS (SELECT satellite, ix, iy, daynight, year, month, sum(r_n_all) r_n_all, sum(r_n0) r_n0, sum(r_n0_low) r_n0_low, sum(r_n) r_n, sum(r_frp) r_frp,
                            {', '.join(f'sum(r_c_{b}) r_c_{b}, sum(r_f_{b}) r_f_{b}' for b in B)}
                     FROM read_parquet('{G}/mask_removed/removed_*.parquet') WHERE year = {y} GROUP BY ALL),
          j AS (SELECT m.satellite, m.ix, m.iy, m.daynight, m.year, m.month,
                 greatest(m.n_sum - coalesce(r.r_n, 0), 0) AS n_sum2, greatest(m.frp_sum - coalesce(r.r_frp, 0), 0) AS frp_sum2, m.n_sum AS n_old, m.frp_sum AS frp_old,
                 m.n_best, m.frp_best, m.nsub_best, m.days, m.ops,
                 greatest(m.n_all - coalesce(r.r_n_all, 0), 0) AS n_all, greatest(m.n0 - coalesce(r.r_n0, 0), 0) AS n0, greatest(m.n0_low - coalesce(r.r_n0_low, 0), 0) AS n0_low,
                 m.n_static, m.n_volc, m.n_offshore, m.scan_mean, m.lst, {sub}
                FROM '{f}' m LEFT JOIN r USING (satellite, ix, iy, daynight, year, month))
          SELECT satellite, ix, iy, daynight, year, month, CAST(n_sum2 AS INT) AS n_sum, CAST(frp_sum2 AS FLOAT) AS frp_sum,
                 CAST(round(n_best * CASE WHEN n_old > 0 THEN n_sum2 / n_old ELSE 1 END) AS INT) AS n_best,
                 CAST(frp_best * CASE WHEN frp_old > 0 THEN frp_sum2 / frp_old ELSE 1 END AS FLOAT) AS frp_best,
                 CAST(round(nsub_best * CASE WHEN n_old > 0 THEN n_sum2 / n_old ELSE 1 END) AS INT) AS nsub_best,
                 days, ops, CAST(n_all AS INT) AS n_all, CAST(n0 AS INT) AS n0, CAST(n0_low AS INT) AS n0_low, n_static, n_volc, n_offshore, scan_mean, lst,
                 {', '.join(f'CAST(c_{b} AS INT) AS c_{b}, CAST(f_{b} AS FLOAT) AS f_{b}' for b in B)}
          FROM j WHERE n_all > 0) TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    print(con.execute(f"""SELECT a.satellite, a.daynight, a.n, b.n, round(100 * (1 - b.n / a.n), 2) pct_removed, round(100 * (1 - b.f / a.f), 2) pct_frp_removed FROM
        (SELECT satellite, daynight, sum(n_sum) n, sum(frp_sum) f FROM read_parquet('{G}/monthly_025_nomask/*.parquet') GROUP BY ALL) a JOIN
        (SELECT satellite, daynight, sum(n_sum) n, sum(frp_sum) f FROM read_parquet('{G}/monthly_025/*.parquet') GROUP BY ALL) b USING (satellite, daynight) ORDER BY 1, 2""").fetchall())
    print('DONE')
