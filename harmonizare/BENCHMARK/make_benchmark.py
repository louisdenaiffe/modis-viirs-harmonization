"""make_benchmark.py — build the common test set + OUR back-cast predictions on the VIIRS scale (run from the project folder).
Truth = real S-NPP VIIRS monthly values per 0.25 deg cell (FIRMS type 0, confidence not low). Our prediction uses ONLY Aqua MODIS."""
import duckdb, pandas as pd, numpy as np, sys, importlib.util
R = 'harmonizare'; sys.path.insert(0, f'{R}/scripts'); import eval_common as ec
s = importlib.util.spec_from_file_location('rev', f'{R}/rezultate/calib_ratio/apply_model_reverse.py'); rev = importlib.util.module_from_spec(s); s.loader.exec_module(rev)
con = duckdb.connect(); con.execute("SET memory_limit='900MB'; SET threads=2"); K = ['ix', 'iy', 'year', 'month', 'daynight']
def q(tab, sat): return con.execute(f"SELECT {', '.join(K)}, n_sum, frp_sum FROM read_parquet('{R}/data/grid/{tab}/*.parquet') WHERE satellite='{sat}' AND year BETWEEN 2018 AND 2023").df()
a = q('monthly_025', 'Aqua'); p = rev.predict(a).reset_index(drop=True)
ours = a[K].copy(); ours['pred_n'] = p.pred_n.values; ours['pred_frp'] = p.pred_frp.values; ours['aqua_n'] = a.n_sum.values; ours['aqua_frp'] = a.frp_sum.values
vm = q('monthly_025', 'SNPP').rename(columns={'n_sum': 'viirs_n_masked', 'frp_sum': 'viirs_frp_masked'})
vn = q('monthly_025_nomask', 'SNPP').rename(columns={'n_sum': 'viirs_n', 'frp_sum': 'viirs_frp'})
t = vn.merge(vm, on=K, how='outer').merge(ours, on=K, how='outer').fillna(0)
cc = pd.read_parquet(f'{R}/rezultate/events_countries/cell_country.parquet')[['ix', 'iy', 'country']]
t = t.merge(cc, on=['ix', 'iy'], how='left'); t['country'] = t.country.fillna('unassigned'); t['region'] = ec.region_of(t.ix.values, t.iy.values).astype(str)
comp = pd.read_csv(f'{R}/rezultate/qc_stability/completeness_monthly.csv')
bad = set(map(tuple, comp[(comp.flag_month != 'ok') & comp.satellite.isin(['Aqua', 'Terra', 'SNPP'])][['year', 'month']].values))
t['month_ok'] = ~t[['year', 'month']].apply(tuple, axis=1).isin(bad)
for c in ('ix', 'iy', 'year', 'month'): t[c] = t[c].astype('int16')
for c in ('viirs_n', 'viirs_frp', 'viirs_n_masked', 'viirs_frp_masked', 'pred_n', 'pred_frp', 'aqua_n', 'aqua_frp'): t[c] = t[c].astype('float32')
t.to_parquet(f'{R}/BENCHMARK/truth_and_ours_2018_2023.parquet', index=False, compression='zstd')
print(len(t), t.month_ok.mean().round(3), sorted(b for b in bad if 2018 <= b[0] <= 2023))
print(t[t.month_ok].groupby('year')[['viirs_n', 'viirs_n_masked', 'pred_n', 'aqua_n']].sum().round(0).to_string())
