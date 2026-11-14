"""b1: count detections per (ix, iy, country) in each remaining points file (resumable, one file per call)."""
import duckdb, os, sys
W = 'work/events_countries'
c = duckdb.connect()
c.sql("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='data/_ducktmp/events_countries'")
for s in ['modis', 'viirs']:
    for y in [2015, 2019, 2021]:
        out = f'{W}/_cc_{s}_{y}.parquet'
        if os.path.exists(out):
            continue
        c.sql(f"""COPY (SELECT ix, iy, country, count(*)::INT AS n FROM 'data/points/{s}_{y}.parquet'
                  GROUP BY ALL) TO '{out}' (FORMAT parquet)""")
        print('done', out, flush=True)
        if len(sys.argv) < 2: sys.exit(0)
