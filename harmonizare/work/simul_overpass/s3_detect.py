"""Step 3: P(Aqua detects | S-NPP 0.01-deg cluster FRP). Usage: python3 s3_detect.py YEAR MONTH [MONTH...]
Sample: S-NPP overpass-cells where Aqua detected fire in >=1 of the 8 neighbouring 0.25-deg cells within +-10 min (ring10).
Cluster = S-NPP pixels (type 0, conf not low) of one overpass in one 0.01-deg sub-cell (sx,sy); FRP summed.
Detected = an Aqua pixel within +-10 min whose footprint box (scan km E-W x track km N-S, centred on pixel) contains the
cluster centroid. det_q: Aqua pixel type 0 & conf not low (team target definition); det_any: any Aqua pixel.
Scan proxy = mean Aqua scan in own cell for that overpass if Aqua detected there, else mean over the 8 neighbour cells.
det_tol: as det_q but box doubled (2*scan x 2*track), tolerates PSF/geolocation spread.
Writes s3/hist_{y}_{m}.parquet (aggregated)."""
import sys, os, time; sys.path.insert(0, os.path.dirname(__file__)); from common import *
y = int(sys.argv[1]); os.makedirs(f'{W}/s3', exist_ok=True); c = con()
for m in [int(a) for a in sys.argv[2:]]:
    out = f'{W}/s3/hist_{y}_{m:02d}.parquet'
    if os.path.exists(out) and os.path.getsize(out) > 0: continue
    t = time.time()
    c.execute(f"""CREATE OR REPLACE TEMP TABLE VR AS SELECT ix, iy, tv, dn, coalesce(sc_own, sc_ring) sc FROM '{W}/s1/vops_{y}.parquet'
                  WHERE ring10 AND month(tv)={m}""")
    c.execute(f"""CREATE OR REPLACE TEMP TABLE CL AS SELECT p.ix, p.iy, r.tv, r.dn, r.sc, p.sx, p.sy, min(p.ts) tc, count(*) npix, sum(p.frp) frp,
                  avg(p.lat) lat, avg(p.lon) lon
                  FROM '{ROOT}/data/points/viirs_{y}.parquet' p JOIN VR r ON p.ix=r.ix AND p.iy=r.iy AND p.ts BETWEEN r.tv AND r.tv + INTERVAL 20 MINUTE
                  WHERE month(p.acq_date)={m} AND p.type=0 AND p.conf_class<>'l' GROUP BY p.ix, p.iy, r.tv, r.dn, r.sc, p.sx, p.sy""")
    c.execute(f"""CREATE OR REPLACE TEMP TABLE AQ AS
      WITH a AS (SELECT lat, lon, ts, scan, track, (type=0 AND conf_class<>'l') q,
                   scan/2/(111.32*cos(radians(lat))) dlo, track/2/111.32 dla, scan/(111.32*cos(radians(lat))) dlo2, track/111.32 dla2
                 FROM '{ROOT}/data/points/modis_{y}.parquet' WHERE satellite='Aqua' AND month(acq_date)={m})
      SELECT a.*, gx ix, gy iy FROM a,
        unnest(range(CAST(floor((lon-dlo2+180)/0.25) AS INT), CAST(floor((lon+dlo2+180)/0.25) AS INT)+1)) t1(gx),
        unnest(range(CAST(floor((lat-dla2+90)/0.25) AS INT), CAST(floor((lat+dla2+90)/0.25) AS INT)+1)) t2(gy)""")
    c.execute(f"""COPY (
      WITH d AS (SELECT k.ix, k.iy, k.tv, k.sx, k.sy, bool_or(a.q AND abs(a.lat-k.lat) <= a.dla AND abs(a.lon-k.lon) <= a.dlo) dq, bool_or(abs(a.lat-k.lat) <= a.dla AND abs(a.lon-k.lon) <= a.dlo) da, bool_or(a.q) dt2 FROM CL k JOIN AQ a ON k.ix=a.ix AND k.iy=a.iy
                 AND a.ts BETWEEN k.tc - INTERVAL 10 MINUTE AND k.tc + INTERVAL 10 MINUTE
                 AND abs(a.lat-k.lat) <= 2*a.dla AND abs(a.lon-k.lon) <= 2*a.dlo GROUP BY ALL)
      SELECT {y} yr, {m} mo, k.dn, CASE WHEN k.frp<=0 THEN -9 ELSE floor(log10(k.frp)*10)/10 END lbin,
             CASE WHEN k.sc IS NULL THEN 'na' WHEN k.sc<1.5 THEN '1.0-1.5' WHEN k.sc<2 THEN '1.5-2.0' WHEN k.sc<3 THEN '2.0-3.0' ELSE '3.0-4.8' END scb,
             count(*) ncl, sum(k.npix) npix, sum(k.frp) frp,
             count(*) FILTER (coalesce(d.dq,false)) det_q, count(*) FILTER (coalesce(d.da,false)) det_any, count(*) FILTER (coalesce(d.dt2,false)) det_tol, sum(k.frp) FILTER (coalesce(d.dt2,false)) frp_det_tol, sum(k.npix) FILTER (coalesce(d.dt2,false)) npix_det_tol,
             sum(k.npix) FILTER (coalesce(d.dq,false)) npix_det_q, sum(k.frp) FILTER (coalesce(d.dq,false)) frp_det_q
      FROM CL k LEFT JOIN d USING (ix, iy, tv, sx, sy) GROUP BY ALL) TO '{out}' (FORMAT PARQUET)""")
    print(y, m, c.execute("select count(*) from CL").fetchone()[0], 'clusters', round(time.time()-t), 's', flush=True)
