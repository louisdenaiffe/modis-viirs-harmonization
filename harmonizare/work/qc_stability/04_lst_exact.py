"""Exact median local solar time per satellite x year x daynight x lat band (hemispheres pooled), type 0 detections."""
import duckdb, os, glob, pandas as pd
R = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
c = duckdb.connect(); c.execute(f"SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='{R}/data/_ducktmp/qc_stability'")
out = []
for f in sorted(glob.glob(f'{R}/data/points/*.parquet')):
    out.append(c.execute(f"""SELECT satellite, daynight, year(acq_date) yr,
        CASE WHEN abs(lat)<23.5 THEN 'tropics' WHEN abs(lat)<50 THEN 'mid_23-50' ELSE 'high_50+' END band,
        median(lst) lst_med, quantile_cont(lst,0.25) lst_q25, quantile_cont(lst,0.75) lst_q75, count(*) n
        FROM read_parquet('{f}') WHERE type=0 GROUP BY ALL""").df())
    out.append(c.execute(f"""SELECT satellite, daynight, year(acq_date) yr, 'all' band, median(lst) lst_med, quantile_cont(lst,0.25) lst_q25,
        quantile_cont(lst,0.75) lst_q75, count(*) n FROM read_parquet('{f}') WHERE type=0 GROUP BY ALL""").df())
pd.concat(out).to_parquet(f'{R}/work/qc_stability/lst_pooled.parquet')
