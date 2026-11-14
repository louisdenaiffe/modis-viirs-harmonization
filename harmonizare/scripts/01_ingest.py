"""01_ingest.py — FIRMS country CSVs -> one typed Parquet per sensor-year.
Run from the project folder:  python3 harmonizare/scripts/01_ingest.py [time_budget_seconds]
Skips years already converted. Original CSVs are never modified.
Derived columns: sensor, country, ts (UTC), lst (local solar hour), conf_class (l/n/h),
cell025 ids (ix, iy), sub-cell 0.01 deg ids (sx, sy)."""
import duckdb, glob, os, sys, time, re
budget = float(sys.argv[1]) if len(sys.argv) > 1 else 150
t0 = time.time()
con = duckdb.connect(); con.execute("SET memory_limit='1800MB'; SET threads=4; SET preserve_insertion_order=false")
out = 'harmonizare/data/points'
jobs = []
for sensor, root, bcol, b2col in [('MODIS','MODIS data','brightness','bright_t31'), ('VIIRS','VIIRS data','bright_ti4','bright_ti5')]:
    for d in sorted(glob.glob(f'{root}/*/[12][0-9][0-9][0-9]')):
        jobs.append((sensor, int(os.path.basename(d)), d, bcol, b2col))
jobs.sort(key=lambda j: (j[1], j[0]))
for sensor, year, d, bcol, b2col in jobs:
    dst = f'{out}/{sensor.lower()}_{year}.parquet'
    if os.path.exists(dst): continue
    if time.time() - t0 > budget: print('budget reached; rerun to continue'); break
    t = time.time(); tmp = os.path.expanduser(f'~/tmp_{sensor}_{year}.parquet')
    conf = ("CASE WHEN TRY_CAST(confidence AS INT) < 30 THEN 'l' WHEN TRY_CAST(confidence AS INT) < 80 THEN 'n' ELSE 'h' END"
            if sensor == 'MODIS' else "lower(confidence)")
    con.execute(f"""
    COPY (
      WITH r AS (
        SELECT *, lpad(acq_time, 4, '0') AS hhmm,
               regexp_extract(filename, '_[0-9]{{4}}_(.*)\\.csv$', 1) AS country
        FROM read_csv('{d}/*.csv', filename=true, union_by_name=true,
             types={{'acq_time':'VARCHAR','confidence':'VARCHAR','version':'VARCHAR','satellite':'VARCHAR'}})
      )
      SELECT '{sensor}' AS sensor,
             CASE WHEN satellite='N' THEN 'SNPP' ELSE satellite END AS satellite,
             country,
             CAST(latitude AS DOUBLE) AS lat, CAST(longitude AS DOUBLE) AS lon,
             CAST(acq_date AS DATE) AS acq_date, hhmm,
             CAST(acq_date AS TIMESTAMP) + to_minutes(CAST(substr(hhmm,1,2) AS INT)*60 + CAST(substr(hhmm,3,2) AS INT)) AS ts,
             CAST(((CAST(substr(hhmm,1,2) AS INT) + CAST(substr(hhmm,3,2) AS INT)/60.0 + longitude/15.0 + 48) % 24) AS FLOAT) AS lst,
             daynight,
             CAST(scan AS FLOAT) AS scan, CAST(track AS FLOAT) AS track,
             CAST(frp AS FLOAT) AS frp,
             CAST({bcol} AS FLOAT) AS bt_fire, CAST({b2col} AS FLOAT) AS bt_bg,
             confidence AS conf_raw, {conf} AS conf_class,
             version, CAST(type AS TINYINT) AS type,
             CAST(floor((longitude + 180) / 0.25) AS SMALLINT) AS ix, CAST(floor((latitude + 90) / 0.25) AS SMALLINT) AS iy,
             CAST(floor((longitude + 180) / 0.01) AS INT) AS sx, CAST(floor((latitude + 90) / 0.01) AS INT) AS sy
      FROM r
    ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 500000)""")
    n = con.execute(f"SELECT count(*) FROM '{tmp}'").fetchone()[0]
    import shutil; shutil.copyfile(tmp, dst); os.remove(tmp)
    print(f'{sensor} {year}: {n:,} rows, {os.path.getsize(dst)/1e6:.0f} MB, {time.time()-t:.0f}s', flush=True)
print('done pass', round(time.time()-t0), 's')
