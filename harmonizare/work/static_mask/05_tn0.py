"""Per satellite x year x 0.01 cell: type 1/2/3 detections, distinct days, month mask, night count -> work/static_mask/tn0.parquet"""
import duckdb, time
t=time.time(); c=duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='harmonizare/data/_ducktmp/static_mask'")
c.execute("""COPY (SELECT satellite, year(acq_date)::SMALLINT yr, sx, sy, count(*) FILTER (type=1)::INT t1, count(*) FILTER (type=2)::INT t2, count(*) FILTER (type=3)::INT t3,
  count(*) FILTER (daynight='N')::INT tN, count(DISTINCT acq_date)::SMALLINT tdays, bit_or(1::SMALLINT << (month(acq_date)-1)::SMALLINT)::SMALLINT tmask
  FROM 'harmonizare/data/points/*.parquet' WHERE type<>0 GROUP BY ALL) TO 'harmonizare/work/static_mask/tn0.parquet' (FORMAT PARQUET)""")
print(c.execute("SELECT satellite, count(*), sum(t1+t2+t3) FROM 'harmonizare/work/static_mask/tn0.parquet' GROUP BY 1").df(), time.time()-t)
