"""Step 1: coincident Aqua / S-NPP overpasses on the 0.25 deg grid, per year (resumable).
Outputs work/simul_overpass/s1/pairs_{y}.parquet (|dt|<=30 min, same cell),
        s1/vops_{y}.parquet (every S-NPP overpass-cell with flags: Aqua same cell +-10 min, Aqua in 8-neighbour ring +-10 min,
        Aqua scan proxy), s1/aops_{y}.parquet (Aqua overpass-cells with symmetric flags)."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__)); from common import *
os.makedirs(f'{W}/s1', exist_ok=True)
years = [int(a) for a in sys.argv[1:]] or list(range(2012, 2022))
c = con()
for y in years:
    if os.path.exists(f'{W}/s1/aops_{y}.parquet'): continue
    t = time.time()
    c.execute(f"""CREATE OR REPLACE TEMP TABLE A AS SELECT ix, iy, t_start ta, daynight dn, n0q, frp0q, n0, frp0, n_all, scan_mean, scan_max
                  FROM '{ROOT}/data/grid/op_modis_{y}.parquet' WHERE satellite='Aqua'""")
    c.execute(f"""CREATE OR REPLACE TEMP TABLE V AS SELECT ix, iy, t_start tv, daynight dn, n0q, frp0q, n0, frp0, n_all, scan_mean
                  FROM '{ROOT}/data/grid/op_viirs_{y}.parquet'""")
    c.execute(f"""COPY (SELECT v.ix, v.iy, v.dn, v.tv, a.ta, date_diff('minute', a.ta, v.tv) dt,
                  v.n0q vn0q, v.frp0q vfrp0q, v.n0 vn0, a.n0q an0q, a.frp0q afrp0q, a.n0 an0, a.frp0 afrp0, a.scan_mean ascan
                  FROM V v JOIN A a ON v.ix=a.ix AND v.iy=a.iy AND a.ta BETWEEN v.tv - INTERVAL 30 MINUTE AND v.tv + INTERVAL 30 MINUTE)
              TO '{W}/s1/pairs_{y}.parquet' (FORMAT PARQUET)""")
    # neighbourhood expansion of Aqua ops (ring of 8 neighbours, plus own cell flag)
    def flags(X, tx, Y, ty, out, extra):
        c.execute(f"""COPY (
          WITH E AS (SELECT y.ix+dx ix, y.iy+dy iy, y.{ty} t, (dx=0 AND dy=0) own, y.scan_mean sc
                     FROM {Y} y, (SELECT unnest(range(-1,2)) dx) a, (SELECT unnest(range(-1,2)) dy) b),
          M AS (SELECT x.ix, x.iy, x.{tx}, bool_or(e.own) same10, bool_or(NOT e.own) ring10,
                       avg(e.sc) FILTER (e.own) sc_own, avg(e.sc) FILTER (NOT e.own) sc_ring
                FROM {X} x JOIN E e ON x.ix=e.ix AND x.iy=e.iy AND e.t BETWEEN x.{tx} - INTERVAL 10 MINUTE AND x.{tx} + INTERVAL 10 MINUTE
                GROUP BY ALL)
          SELECT x.ix, x.iy, x.{tx}, x.dn, x.n0q, x.frp0q, x.n0, {extra}
                 coalesce(m.same10,false) same10, coalesce(m.ring10,false) ring10, m.sc_own, m.sc_ring
          FROM {X} x LEFT JOIN M m ON x.ix=m.ix AND x.iy=m.iy AND x.{tx}=m.{tx}) TO '{out}' (FORMAT PARQUET)""")
    flags('V', 'tv', 'A', 'ta', f'{W}/s1/vops_{y}.parquet', '')
    flags('A', 'ta', 'V', 'tv', f'{W}/s1/aops_{y}.parquet', 'x.scan_mean,')
    print(y, round(time.time()-t), 's', flush=True)
