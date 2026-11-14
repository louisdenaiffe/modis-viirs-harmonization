"""Step 2: footprint-scale match. Usage: python3 s2_footprint.py YEAR MONTH [MONTH...]
For every Aqua pixel (type 0, conf not low) in a coincident cell-overpass (S-NPP overpass in same 0.25-deg cell, |dt|<=10 min),
sum S-NPP pixels (type 0, any confidence -> column v*, and conf not low -> v*q) whose centres fall in the Aqua footprint box
(scan km E-W x track km N-S centred on the Aqua pixel; approximation: scan direction taken as exactly E-W) within +-10 min.
Also nv2/vfrp2: same with box doubled (2*scan x 2*track).
Writes s2/px_{y}_{m}.parquet: one row per Aqua pixel."""
import sys, os, time; sys.path.insert(0, os.path.dirname(__file__)); from common import *
y = int(sys.argv[1]); os.makedirs(f'{W}/s2', exist_ok=True); c = con()
for m in [int(a) for a in sys.argv[2:]]:
    out = f'{W}/s2/px_{y}_{m:02d}.parquet'
    if os.path.exists(out) and os.path.getsize(out) > 0: continue
    t = time.time()
    c.execute(f"""CREATE OR REPLACE TEMP TABLE PR AS SELECT DISTINCT ix, iy, ta FROM '{W}/s1/pairs_{y}.parquet' WHERE abs(dt)<=10 AND month(ta)={m}""")
    c.execute(f"""CREATE OR REPLACE TEMP TABLE MP AS SELECT row_number() OVER () id, p.lat, p.lon, p.ts, p.scan, p.track, p.frp, p.daynight dn,
                  p.scan/2/(111.32*cos(radians(p.lat))) dlo, p.track/2/111.32 dla
                  FROM '{ROOT}/data/points/modis_{y}.parquet' p JOIN PR r ON p.ix=r.ix AND p.iy=r.iy AND p.ts BETWEEN r.ta AND r.ta + INTERVAL 20 MINUTE
                  WHERE p.satellite='Aqua' AND month(p.acq_date)={m} AND p.type=0 AND p.conf_class<>'l'""")
    c.execute(f"""CREATE OR REPLACE TEMP TABLE ME AS SELECT id, lat, lon, ts, dlo, dla, gx ix, gy iy FROM MP,
        unnest(range(CAST(floor((lon-2*dlo+180)/0.25) AS INT), CAST(floor((lon+2*dlo+180)/0.25) AS INT)+1)) t1(gx),
        unnest(range(CAST(floor((lat-2*dla+90)/0.25) AS INT), CAST(floor((lat+2*dla+90)/0.25) AS INT)+1)) t2(gy)""")
    c.execute(f"""COPY (WITH v AS (SELECT p.ix, p.iy, p.lat, p.lon, p.ts, p.frp, p.conf_class<>'l' q FROM '{ROOT}/data/points/viirs_{y}.parquet' p
                  SEMI JOIN (SELECT DISTINCT ix, iy FROM ME) k ON p.ix=k.ix AND p.iy=k.iy WHERE month(p.acq_date)={m} AND p.type=0),
      s AS (SELECT e.id, count(*) FILTER (x) nv, coalesce(sum(v.frp) FILTER (x),0) vfrp, count(*) FILTER (x AND v.q) nvq, coalesce(sum(v.frp) FILTER (x AND v.q),0) vfrpq,
                   count(*) nv2, sum(v.frp) vfrp2
            FROM ME e JOIN v ON e.ix=v.ix AND e.iy=v.iy AND v.ts BETWEEN e.ts - INTERVAL 10 MINUTE AND e.ts + INTERVAL 10 MINUTE
            AND abs(v.lat-e.lat) <= 2*e.dla AND abs(v.lon-e.lon) <= 2*e.dlo,
            LATERAL (SELECT abs(v.lat-e.lat) <= e.dla AND abs(v.lon-e.lon) <= e.dlo AS x) GROUP BY 1)
      SELECT {y} yr, {m} mo, m.dn, m.lat, m.scan, m.track, m.frp mfrp, coalesce(s.nv,0) nv, coalesce(s.vfrp,0) vfrp, coalesce(s.nvq,0) nvq, coalesce(s.vfrpq,0) vfrpq, coalesce(s.nv2,0) nv2, coalesce(s.vfrp2,0) vfrp2
      FROM MP m LEFT JOIN s USING (id)) TO '{out}' (FORMAT PARQUET)""")
    print(y, m, c.execute("select count(*) from MP").fetchone()[0], 'aqua px', round(time.time()-t), 's', flush=True)
