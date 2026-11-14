"""Small feature table of candidate cells (any type 1/2/3, or >=8 type-0q days in some satellite-year) -> feat.parquet"""
import duckdb, time
t=time.time()
c=duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='../../data/_ducktmp/static_mask'")
c.execute("""COPY (SELECT satellite, yr, sx, sy, n_t1, n_t2, n_t3, nD, nN, fD, fN, days0q, nmon, mmask FROM 'cells/*.parquet'
  WHERE n_t1+n_t2+n_t3>0 OR days0q>=8) TO 'feat.parquet' (FORMAT PARQUET)""")
print(c.execute("SELECT satellite, count(*), sum(n_t1+n_t2+n_t3>0::INT) FROM 'feat.parquet' GROUP BY 1").df(), time.time()-t)
