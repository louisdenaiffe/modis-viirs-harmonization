"""Pass 1 (resumable): points -> per satellite x 0.01 deg cell x quarter stats, for the sample years in data/points.
Run from project folder: python3 harmonizare/work/static_mask/01_cellyear.py [budget_s]
Quarters have disjoint days, so days can be summed and month masks OR-ed later."""
import duckdb, glob, os, sys, time, shutil
B = float(sys.argv[1]) if len(sys.argv) > 1 else 70; t0 = time.time()
W = 'harmonizare/work/static_mask/cy'; os.makedirs(W, exist_ok=True)
c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='harmonizare/data/_ducktmp/static_mask'")
for f in sorted(glob.glob('harmonizare/data/points/*.parquet')):
    nm = os.path.basename(f).replace('.parquet', '')
    o2 = f'{W}/types_{nm}.parquet'
    if not os.path.exists(o2):
        c.execute(f"""COPY (SELECT satellite, daynight, type, conf_class, count(*) n, sum(frp) frp FROM '{f}' GROUP BY ALL) TO '{o2}'""")
        print('types', nm, round(time.time()-t0), flush=True)
    for q0 in (1, 4, 7, 10):
        po = f'{W}/part_{nm}_{q0:02d}.parquet'
        if os.path.exists(po): continue
        if time.time() - t0 > B: print('budget'); sys.exit()
        t = time.time(); tmp = os.path.expanduser(f'~/sm_tmp_{nm}_{q0}.parquet')
        c.execute(f"""COPY (
          WITH d AS (SELECT satellite, sx, sy, acq_date,
              count(*) FILTER (type<>0) n_tn0,
              count(*) FILTER (type=1) n_t1, count(*) FILTER (type=2) n_t2, count(*) FILTER (type=3) n_t3,
              count(*) FILTER (type=0 AND conf_class<>'l' AND daynight='D') nD,
              count(*) FILTER (type=0 AND conf_class<>'l' AND daynight='N') nN,
              sum(frp) FILTER (type=0 AND conf_class<>'l' AND daynight='D') fD,
              sum(frp) FILTER (type=0 AND conf_class<>'l' AND daynight='N') fN
            FROM '{f}' WHERE month(acq_date) BETWEEN {q0} AND {q0+2} GROUP BY ALL)
          SELECT satellite, {nm[-4:]}::SMALLINT yr, sx, sy,
              sum(n_t1)::INT n_t1, sum(n_t2)::INT n_t2, sum(n_t3)::INT n_t3,
              sum(nD)::INT nD, sum(nN)::INT nN, coalesce(sum(fD),0)::FLOAT fD, coalesce(sum(fN),0)::FLOAT fN,
              (count(*) FILTER (nD+nN>0))::SMALLINT days0q,
              coalesce(bit_or(1::SMALLINT << (month(acq_date)-1)::SMALLINT) FILTER (nD+nN>0),0)::SMALLINT mmask
          FROM d GROUP BY satellite, sx, sy) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
        shutil.copyfile(tmp, po); os.remove(tmp)
        print(' part', nm, q0, round(time.time()-t), 's', os.path.getsize(po)//1e6, 'MB', flush=True)
print('ALL DONE', round(time.time()-t0))
