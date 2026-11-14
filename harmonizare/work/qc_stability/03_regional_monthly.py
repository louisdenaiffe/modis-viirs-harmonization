"""Aggregate monthly_025 to satellite x year x month x daynight x eval region x lat band."""
import duckdb, numpy as np, pandas as pd, os, sys
R = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')); sys.path.insert(0, f'{R}/scripts')
from eval_common import region_of
c = duckdb.connect(); c.execute(f"SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='{R}/data/_ducktmp/qc_stability'")
cells = pd.DataFrame({'ix': np.repeat(np.arange(1440), 720).astype('int16'), 'iy': np.tile(np.arange(720), 1440).astype('int16')})
cells['region'] = region_of(cells.ix.values, cells.iy.values); lat = (cells.iy + 0.5) * 0.25 - 90
cells['band'] = np.where(lat.abs() < 23.5, 'tropics', np.where(lat.abs() < 50, 'mid_23-50', 'high_50+'))
c.register('cells', cells)
df = c.execute(f"""SELECT satellite, year, month, daynight, region, band, sum(n_sum) n_sum, sum(frp_sum) frp_sum, sum(n_all) n_all,
    sum(ops) ops FROM read_parquet('{R}/data/grid/monthly_025/*.parquet') JOIN cells USING (ix, iy) GROUP BY ALL""").df()
df.to_parquet(f'{R}/work/qc_stability/regional_monthly.parquet'); print(len(df)); print(df.groupby('satellite').n_sum.sum())
