"""calib_ratio v2 = v1 (B5) everywhere, except DAYTIME COUNTS in BONA and BOAS:
   there the VIIRS input is n_best (strongest overpass per day, removes the multi-overpass effect at high latitude)
   and the regions are split at 60N (BONA_lo/BONA_hi, BOAS_lo/BOAS_hi); same B5 recipe (season x shrunk cell, same n0).
   Validated on calibration years (leave-one-year-out) and on 2018-2021. Everything else identical to apply_model.py.
Usage: import apply_model_v2 as am2; out = am2.predict(df)  # df: ix, iy, year, month, daynight, n_sum, frp_sum, n_best
       (if n_best is missing, BONA/BOAS day counts fall back to v1)"""
import os, sys, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import apply_model as v1
BO = ('BONA', 'BOAS'); VAR2 = 'n_best_hilat'; _KEYS_V1 = v1._keys
def _keys_split(d):
    d = _KEYS_V1(d); lat = (d.iy + 0.5) * 0.25 - 90; m = d.region.isin(BO)
    d.loc[m, 'region'] = d.loc[m, 'region'] + np.where(lat[m] >= 60, '_hi', '_lo'); return d
def fit_factors_v2(cal):
    """cal: paired cell-months with ix,iy,month,daynight,a_n,a_frp,s_n,s_frp,s_nb"""
    F = v1.fit_factors(cal[['ix', 'iy', 'year', 'month', 'daynight', 'a_n', 'a_frp', 's_n', 's_frp']])
    reg = v1.ec.region_of(cal.ix.values, cal.iy.values); c = cal[np.isin(reg, BO) & (cal.daynight.astype(str) == 'D').values].copy(); c['s_n'] = c.s_nb
    v1._keys = _keys_split
    try: G = v1.fit_factors(c[['ix', 'iy', 'year', 'month', 'daynight', 'a_n', 'a_frp', 's_n', 's_frp']])
    finally: v1._keys = _KEYS_V1
    G = G[(G['var'] == 'n') & G.region.str[:4].isin(BO)].copy(); G['var'] = VAR2
    return pd.concat([F, G], ignore_index=True)
def load_factors():
    return pd.read_parquet(f'{HERE}/factors_v2.parquet')
def predict(df, F=None, interval=True):
    F = load_factors() if F is None else F
    out = v1.predict(df, F[F['var'] != VAR2], interval)
    if 'n_best' not in df: return out
    reg = v1.ec.region_of(df.ix.values, df.iy.values); m = np.isin(reg, BO) & (df.daynight.astype(str).values == 'D')
    if not m.any(): return out
    sub = df[m].copy(); sub['n_sum'] = sub.n_best
    G = F[F['var'] == VAR2].copy(); G['var'] = 'n'
    G = pd.concat([G, F[(F['var'] == 'n') & F.level.str.startswith('interval')], F[F['var'] == 'frp']], ignore_index=True)
    v1._keys = _keys_split
    try: p = v1.predict(sub, G, interval)
    finally: v1._keys = _KEYS_V1
    for c in ('pred_n', 'lo_n', 'hi_n'):
        if c in p: out.loc[m, c] = p[c].values
    return out
