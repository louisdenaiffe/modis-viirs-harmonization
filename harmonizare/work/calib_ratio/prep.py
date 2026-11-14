# Build paired Aqua/SNPP cell-month table per year (2012-2021) + regional monthly Aqua 2003-2021
import sys, os, duckdb, numpy as np, pandas as pd
sys.path.insert(0, 'scripts'); import eval_common as ec
W = 'work/calib_ratio'
c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='data/_ducktmp/calib_ratio'")
cells = pd.DataFrame({'ix': np.repeat(np.arange(1440), 720).astype('int16'), 'iy': np.tile(np.arange(720), 1440).astype('int16')})
cells['region'] = ec.region_of(cells.ix.values, cells.iy.values).astype(str)
c.register('cells', cells)
M = 'data/grid/monthly_025/monthly_{}.parquet'
cols = "n_sum n, frp_sum frp, n_best nb, frp_best fb, nsub_best sb, days d, scan_mean scan"
for y in range(2012, 2022):
    out = f'{W}/pair_{y}.parquet'
    if os.path.exists(out): continue
    c.execute(f"""COPY (WITH a AS (SELECT ix,iy,year,month,daynight,{cols} FROM read_parquet('{M.format(y)}') WHERE satellite='Aqua'),
      s AS (SELECT ix,iy,year,month,daynight,{cols} FROM read_parquet('{M.format(y)}') WHERE satellite='SNPP')
      SELECT ix,iy,year,month,daynight, region,
        coalesce(a.n,0) a_n, coalesce(a.frp,0)::FLOAT a_frp, coalesce(a.nb,0) a_nb, coalesce(a.fb,0)::FLOAT a_fb, coalesce(a.sb,0) a_sb, coalesce(a.d,0) a_d,
        coalesce(s.n,0) s_n, coalesce(s.frp,0)::FLOAT s_frp, coalesce(s.nb,0) s_nb, coalesce(s.fb,0)::FLOAT s_fb, coalesce(s.sb,0) s_sb, coalesce(s.d,0) s_d
      FROM a FULL OUTER JOIN s USING (ix,iy,year,month,daynight) JOIN cells USING (ix,iy)
      WHERE coalesce(a.n,0)+coalesce(s.n,0) > 0) TO '{out}' (FORMAT parquet)""")
    print(y, c.execute(f"select count(*), sum(a_n), sum(s_n) from '{out}'").fetchall())
out = f'{W}/regmonth_aqua_snpp.parquet'
if not os.path.exists(out):
    c.execute(f"""COPY (SELECT satellite, region, daynight, year, month, sum(n_sum) n, sum(frp_sum) frp, count(*) FILTER (WHERE n_sum>0) cells
      FROM read_parquet('data/grid/monthly_025/*.parquet') JOIN cells USING (ix,iy) WHERE satellite IN ('Aqua','SNPP') AND year BETWEEN 2003 AND 2025 GROUP BY ALL) TO '{out}' (FORMAT parquet)""")
print('done')
