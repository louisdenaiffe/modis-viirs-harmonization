"""Pass over data/points: daily global counts, lst medians by lat band, version x country, country presence. Resumable."""
import duckdb, os, sys, glob, time
R = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = f'{R}/work/qc_stability/pass1'
c = duckdb.connect()
c.execute(f"SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='{R}/data/_ducktmp/qc_stability'")
t0 = time.time()
for f in sorted(glob.glob(f'{R}/data/points/*.parquet')):
    tag = os.path.basename(f)[:-8]
    if os.path.exists(f'{OUT}/{tag}_ver.parquet'): continue
    if time.time() - t0 > 110: print('time budget, rerun'); break
    src = f"read_parquet('{f}')"
    c.execute(f"""COPY (SELECT satellite, daynight, acq_date, count(*) n_all,
        count(*) FILTER (WHERE type=0 AND conf_class<>'l') n0q, sum(frp) FILTER (WHERE type=0 AND conf_class<>'l') frp0q
        FROM {src} GROUP BY ALL) TO '{OUT}/{tag}_daily.parquet'""")
    c.execute(f"""COPY (SELECT satellite, daynight, year(acq_date) yr,
        CASE WHEN abs(lat)<23.5 THEN 'tropics' WHEN abs(lat)<50 THEN 'mid_23-50' ELSE 'high_50+' END band,
        CASE WHEN lat>=0 THEN 'N' ELSE 'S' END hemi,
        median(lst) lst_med, quantile_cont(lst,0.25) lst_q25, quantile_cont(lst,0.75) lst_q75, count(*) n
        FROM {src} WHERE type=0 GROUP BY ALL) TO '{OUT}/{tag}_lst.parquet'""")
    c.execute(f"""COPY (SELECT satellite, country, version, year(acq_date) yr, count(*) n, min(acq_date) d0, max(acq_date) d1
        FROM {src} GROUP BY ALL) TO '{OUT}/{tag}_ver.parquet'""")
    print(tag, round(time.time() - t0), flush=True)
