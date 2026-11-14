"""Combine quarterly parts -> cell-year table per satellite, one file per sensor-year (work/static_mask/cells/)."""
import duckdb, glob, os, time, shutil
os.makedirs('cells', exist_ok=True); t0=time.time()
c=duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='../../data/_ducktmp/static_mask'")
for nm in ['modis_2015','modis_2019','modis_2021','viirs_2015','viirs_2019','viirs_2021']:
    o=f'cells/{nm}.parquet'
    if os.path.exists(o) or time.time()-t0>60: continue
    tmp=os.path.expanduser(f'~/smc_{nm}.parquet')
    c.execute(f"""COPY (SELECT satellite, yr, sx, sy, sum(n_t1)::INT n_t1, sum(n_t2)::INT n_t2, sum(n_t3)::INT n_t3,
      sum(nD)::INT nD, sum(nN)::INT nN, sum(fD)::FLOAT fD, sum(fN)::FLOAT fN, sum(days0q)::SMALLINT days0q,
      bit_count(bit_or(mmask))::TINYINT nmon, bit_or(mmask)::SMALLINT mmask
      FROM read_parquet('cy/part_{nm}_*.parquet') GROUP BY ALL) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    shutil.copyfile(tmp,o); os.remove(tmp); print(nm, round(time.time()-t0), flush=True)
