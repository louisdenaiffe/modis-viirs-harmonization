"""Group masked cells into 0.1 deg sites; rank by default-filter (type 0, not low) detections removed -> top_static_sites_raw.csv"""
import duckdb, pandas as pd
c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2")
OUT = '../../rezultate/static_mask'
q = f"""WITH s AS (SELECT s.*, m.reason FROM 'cells/*.parquet' s JOIN '{OUT}/static_mask_001.parquet' m USING (sx, sy)),
 t AS (SELECT t.*, m.reason FROM 'tn0.parquet' t JOIN '{OUT}/static_mask_001.parquet' m USING (sx, sy))
SELECT a.*, b.n_flag1, b.n_flag2, b.n_flag3 FROM (
 SELECT sx // 10 gx, sy // 10 gy, mode(reason) reason, sum(nD+nN) n0q_removed, sum(nN) n0q_N, sum(nD+nN) FILTER (satellite='SNPP') n0q_snpp,
   sum(nD+nN) FILTER (satellite='Aqua') n0q_aqua, max(days0q) FILTER (satellite='SNPP') max_days_snpp, max(days0q) FILTER (satellite<>'SNPP') max_days_modis,
   max(nmon) FILTER (satellite='SNPP') max_months_snpp, round(sum(fD+fN)/sum(nD+nN),1) mean_frp,
   round(avg((sy+0.5)*0.01-90),3) lat, round(avg((sx+0.5)*0.01-180),3) lon FROM s GROUP BY 1,2) a
LEFT JOIN (SELECT sx // 10 gx, sy // 10 gy, sum(t1) n_flag1, sum(t2) n_flag2, sum(t3) n_flag3 FROM t GROUP BY 1,2) b USING (gx, gy)
ORDER BY n0q_removed DESC"""
d = c.execute(q).df()
d.head(300).to_csv('top_static_sites_raw.csv', index=False)
pd.set_option('display.width', 250); print(d.head(30).drop(columns=['gx','gy']).to_string())
v = c.execute(f"""SELECT sx // 10 gx, sy // 10 gy, round(avg((sy+0.5)*0.01-90),2) lat, round(avg((sx+0.5)*0.01-180),2) lon, sum(t1) n_t1, sum(tdays) flag_days
  FROM 'tn0.parquet' WHERE t1>0 GROUP BY 1,2 ORDER BY n_t1 DESC LIMIT 15""").df(); print(v.to_string()); v.to_csv('top_volcano_raw.csv', index=False)
