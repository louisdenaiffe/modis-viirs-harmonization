# validate apply_model end-to-end on the test years from the raw monthly table and put the hybrid on the leaderboard
import sys, duckdb, pandas as pd; sys.path.insert(0, 'rezultate/calib_physics_ml'); sys.path.insert(0, 'scripts')
import apply_model as am, eval_common as ec
c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2")
out = []
for y in range(2018, 2022):
    df = c.execute(f"SELECT * FROM 'data/grid/monthly_025/monthly_{y}.parquet' WHERE satellite='SNPP'").df()
    df['pred_n'], df['pred_frp'] = am.predict(df); out.append(df[ec.KEYS + ['pred_n', 'pred_frp']])
p = pd.concat(out); print(ec.evaluate(p, 'P3n_P1frp_hybrid', notes='calib_physics_ml apply_model.py default: counts LightGBM P3, FRP region FRP-bin weights P1; run from raw monthly table').drop(columns=['notes','time']).to_string())
