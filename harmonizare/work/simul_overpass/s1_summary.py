"""Step 1 summary from s1/*.parquet (complete years only). Writes rezultate/simul_overpass/s1_*.csv"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__)); from common import *
YRS = [2015, 2016, 2019, 2020, 2021]
c = con(); os.makedirs(R, exist_ok=True)
P = ",".join(f"'{W}/s1/pairs_{y}.parquet'" for y in YRS)
V = ",".join(f"'{W}/s1/vops_{y}.parquet'" for y in YRS)
A = ",".join(f"'{W}/s1/aops_{y}.parquet'" for y in YRS)
q = lambda s: c.execute(s).df()
pp = q(f"""SELECT year(tv) AS yr, dn, count(*) FILTER (abs(dt)<=10) pairs_le10, count(*) FILTER (abs(dt)>10) pairs_10_30,
   sum(vfrp0q) FILTER (abs(dt)<=10)/sum(afrp0q) FILTER (abs(dt)<=10) frp_ratio_cell_le10,
   sum(vn0q) FILTER (abs(dt)<=10)/sum(an0q) FILTER (abs(dt)<=10) count_ratio_cell_le10
   FROM read_parquet([{P}]) GROUP BY ALL ORDER BY 1,2""")
pp.to_csv(f'{R}/s1_pairs_per_year.csv', index=False); print(pp.to_string())
dt = q(f"SELECT dt, count(*) n FROM read_parquet([{P}]) GROUP BY 1 ORDER BY 1"); dt.to_csv(f'{R}/s1_dt_hist.csv', index=False)
print('dt hist:', dict(zip(dt.dt, dt.n)))
lat = q(f"""SELECT floor(((iy+0.5)*0.25-90)/10)*10 lat0, count(*) FILTER (abs(dt)<=10) pairs_le10 FROM read_parquet([{P}]) GROUP BY 1 ORDER BY 1""")
lat.to_csv(f'{R}/s1_pairs_lat.csv', index=False); print(lat.to_string())
for name, F, oth in (('snpp', V, 'Aqua'), ('aqua', A, 'S-NPP')):
    s = q(f"""SELECT dn, count(*) ops, avg(same10::INT) p_same_all, count(*) FILTER (ring10) ops_ring,
       avg(same10::INT) FILTER (ring10) p_same_ring,
       sum(frp0q) FILTER (ring10 AND same10)/sum(frp0q) FILTER (ring10) frpshare_same_ring,
       sum(n0q) FILTER (ring10 AND same10)/sum(n0q) FILTER (ring10) nshare_same_ring
       FROM read_parquet([{F}]) WHERE n0q>0 GROUP BY 1 ORDER BY 1""")
    s.to_csv(f'{R}/s1_onesided_{name}.csv', index=False); print(name, 'ops (n0q>0): was', oth, 'detecting in same cell +-10min'); print(s.to_string())
