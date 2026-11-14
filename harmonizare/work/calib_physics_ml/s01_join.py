# Build per-year joined table: SNPP features + Aqua target per cell x month x daynight
import duckdb, sys, os, numpy as np, pandas as pd
sys.path.insert(0, 'scripts'); import eval_common as ec
W = 'work/calib_physics_ml'
B = ['lt3', '3_6', '6_10', '10_20', '20_50', 'ge50']
def con():
    c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='data/_ducktmp/calib_physics_ml'"); return c
for y in range(2012, 2026):
    out = f'{W}/joined_{y}.parquet'
    if os.path.exists(out): continue
    c = con(); f = f'data/grid/monthly_025/monthly_{y}.parquet'
    vc = ', '.join(['n_sum', 'frp_sum', 'n_best', 'frp_best', 'nsub_best', 'days', 'ops', 'scan_mean', 'n0_low'] + [f'c_{b}' for b in B] + [f'f_{b}' for b in B])
    df = c.execute(f"""WITH v AS (SELECT ix, iy, year, month, daynight, {vc} FROM '{f}' WHERE satellite='SNPP'),
       a AS (SELECT ix, iy, year, month, daynight, n_sum a_n, frp_sum a_frp FROM '{f}' WHERE satellite='Aqua')
       SELECT * FROM v FULL OUTER JOIN a USING (ix, iy, year, month, daynight)""").df()
    for col in df.columns:
        if col not in ('ix', 'iy', 'year', 'month', 'daynight'): df[col] = df[col].fillna(0).astype('float32')
    df['region'] = ec.region_of(df.ix.values, df.iy.values).astype(str)
    df.to_parquet(out, index=False); print(y, len(df), flush=True)
