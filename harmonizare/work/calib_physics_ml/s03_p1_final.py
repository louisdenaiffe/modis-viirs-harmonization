# Final P1 fit on all calibration months (Poisson NNLS, region weights shrunk 25% to global) + global-only; write weights CSV + test predictions
import sys, time; sys.path.insert(0, 'work/calib_physics_ml'); from s02_p1 import *
rows = []; preds = {}
for dn in 'DN':
    d = cal(dn, CB + FB + ['a_n', 'a_frp']); t = test(dn, CB + FB)
    for var, xc, yc in (('n', CB, 'a_n'), ('frp', FB, 'a_frp')):
        W = fit(d, xc, yc, 'pois', 'region')
        Ws = {r: 0.75 * w + 0.25 * W['ALL'] for r, w in W.items()}
        for r, w in Ws.items():
            if r == 'ALL': w = W['ALL']
            rows.append(dict(daynight=dn, var=var, region=r, **{b: round(float(x), 5) for b, x in zip(B, w)},
                             n_cal_rows=int((d.region == r).sum()) if r != 'ALL' else len(d)))
        for nm, WW in (('global', {'ALL': W['ALL']}), ('reg', Ws)):
            preds.setdefault(nm, {}).setdefault(dn, t[['ix', 'iy', 'year', 'month', 'daynight']].copy())[f'pred_{var}'] = pred(t, WW, xc).astype('float32')
w = pd.DataFrame(rows); w.to_csv(f'{R}/p1_weights.csv', index=False); print(w[w.region == 'ALL'].to_string())
for nm, dd in preds.items(): pd.concat(dd.values()).to_parquet(f'work/calib_physics_ml/pred_P1_{nm}.parquet', index=False)
