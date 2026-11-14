# P3: LightGBM at cell-month level. usage: s06_p3.py n|frp [EXCLUDED_REGION]
import sys, time, os, numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, 'work/calib_physics_ml'); from lib import *
t0 = time.time(); var = sys.argv[1]; ex = sys.argv[2] if len(sys.argv) > 2 else None
F0 = ['n_sum', 'frp_sum', 'n_best', 'frp_best', 'nsub_best', 'days', 'ops', 'scan_mean', 'n0_low'] + CB + FB
y = 'a_n' if var == 'n' else 'a_frp'
def prep(d):
    d = d[d.n_sum > 0].copy(); d['lat'] = (d.iy + 0.5) * 0.25 - 90; d['dn'] = (d.daynight == 'N').astype('int8')
    d['reg'] = d.region.cat.codes.astype('int16'); return d
FEAT = F0 + ['lat', 'month', 'dn', 'reg']
d = prep(cal(None, F0 + [y]))
if ex: d = d[d.region != ex]
tr = d[d.year < 2017].sample(frac=0.3, random_state=0); va = d[d.year == 2017].sample(frac=0.5, random_state=1); del d
par = dict(objective='poisson' if var == 'n' else 'tweedie', tweedie_variance_power=1.5, learning_rate=0.08, num_leaves=63,
           min_data_in_leaf=200, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, num_threads=2, verbose=-1)
dt = lgb.Dataset(tr[FEAT], tr[y], categorical_feature=['reg']); dv = lgb.Dataset(va[FEAT], va[y], reference=dt)
m = lgb.train(par, dt, 800, valid_sets=[dv], callbacks=[lgb.early_stopping(30, verbose=False)])
print('trained', len(tr), m.best_iteration, round(time.time() - t0, 1), flush=True)
tag = f'P3_{var}' + (f'_loro_{ex}' if ex else '')
t = test(None, F0); te = prep(t)
p = m.predict(te[FEAT], num_iteration=m.best_iteration)
out = te[['ix', 'iy', 'year', 'month', 'daynight', 'region']].copy(); out[f'pred_{var}'] = p.astype('float32')
if ex:
    obs = test(None, [y]); obs = obs[obs.region == ex]; o = out[out.region == ex]
    r = [dict(region=ex, var=var, dn=dn, bias=o[o.daynight == dn][f'pred_{var}'].sum() / obs[obs.daynight == dn][y].sum() - 1) for dn in 'DN']
    pd.DataFrame(r).to_csv(f'{W}/loro.csv', mode='a', header=not os.path.exists(f'{W}/loro.csv'), index=False); print(r)
else:
    m.save_model(f'{W}/{tag}.txt', num_iteration=m.best_iteration)
    out.drop(columns='region').to_parquet(f'{W}/pred_{tag}.parquet', index=False)
    imp = pd.DataFrame({'feature': FEAT, 'gain': m.feature_importance('gain')}); imp['gain_share'] = (imp.gain / imp.gain.sum()).round(4)
    imp.sort_values('gain', ascending=False).to_csv(f'{R}/p3_importance_{var}.csv', index=False); print(imp.sort_values('gain', ascending=False).head(8).to_string())
print('done', round(time.time() - t0, 1))
