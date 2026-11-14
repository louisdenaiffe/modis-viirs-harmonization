"""apply_model.py (calib_physics_ml) - convert S-NPP VIIRS monthly cell values into Aqua-MODIS-equivalent values.
Input : rows of data/grid/monthly_025/monthly_{year}.parquet with satellite == 'SNPP' (any year 2012-2025).
        Needs ix, iy, month, daynight, n_sum, frp_sum, n_best, frp_best, nsub_best, days, ops, scan_mean, n0_low, c_*, f_*.
Output: predict(df, counts='p3') -> (pred_n, pred_frp) numpy arrays aligned with df rows.
  pred_frp : P1 = sum over 6 VIIRS pixel-FRP classes of w[region, D/N, class] * VIIRS FRP in class (p1_weights.csv)
  pred_n   : counts='p3' -> LightGBM Poisson model (p3_lgbm_counts.txt, best on 2018-2021 test for regions it was trained on)
             counts='p1' -> FRP-class weights like FRP (more robust for regions/conditions outside training, fully explainable)
CLI   : python apply_model.py 2024   -> writes aqua_equiv_2024.parquet next to this file"""
import os, sys, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, f'{ROOT}/scripts'); import eval_common as ec
B = ['lt3', '3_6', '6_10', '10_20', '20_50', 'ge50']
REGS = sorted(set(r[0] for r in ec.REGIONS)) + ['OTHR']
F0 = ['n_sum', 'frp_sum', 'n_best', 'frp_best', 'nsub_best', 'days', 'ops', 'scan_mean', 'n0_low'] + [f'c_{b}' for b in B] + [f'f_{b}' for b in B]
FEAT = F0 + ['lat', 'month', 'dn', 'reg']
_W = pd.read_csv(f'{HERE}/p1_weights.csv'); _M = None

def _p1(df, reg, var):
    cols = [('c_' if var == 'n' else 'f_') + b for b in B]; X = df[cols].fillna(0).values.astype(float); out = np.zeros(len(df))
    for dn in 'DN':
        w = _W[(_W['var'] == var) & (_W.daynight == dn)].set_index('region')[B]
        for r in np.unique(reg):
            m = (reg == r) & (df.daynight.values == dn)
            if m.any(): out[m] = X[m] @ w.loc[r if r in w.index else 'ALL'].values
    return out

def predict(df, counts='p3'):
    global _M
    df = df.reset_index(drop=True); reg = ec.region_of(df.ix.values, df.iy.values).astype(str)
    pred_frp = _p1(df, reg, 'frp')
    if counts == 'p1': return _p1(df, reg, 'n'), pred_frp
    import lightgbm as lgb
    if _M is None: _M = lgb.Booster(model_file=f'{HERE}/p3_lgbm_counts.txt')
    X = df[F0].fillna(0).astype('float32').copy(); X['lat'] = (df.iy.values + 0.5) * 0.25 - 90
    X['month'] = df.month.values; X['dn'] = (df.daynight.values == 'N').astype('int8')
    X['reg'] = pd.Categorical(reg, categories=REGS).codes.astype('int16')
    pred_n = np.where(df.n_sum.values > 0, _M.predict(X[FEAT]), 0.0)
    return pred_n, pred_frp

if __name__ == '__main__':
    import duckdb; y = int(sys.argv[1]); c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2")
    df = c.execute(f"SELECT * FROM '{ROOT}/data/grid/monthly_025/monthly_{y}.parquet' WHERE satellite='SNPP'").df()
    df['pred_n'], df['pred_frp'] = predict(df, sys.argv[2] if len(sys.argv) > 2 else 'p3')
    df[['ix', 'iy', 'year', 'month', 'daynight', 'pred_n', 'pred_frp']].to_parquet(f'{HERE}/aqua_equiv_{y}.parquet', index=False)
    print(y, len(df), df.groupby('daynight')[['n_sum', 'pred_n', 'frp_sum', 'pred_frp']].sum())
