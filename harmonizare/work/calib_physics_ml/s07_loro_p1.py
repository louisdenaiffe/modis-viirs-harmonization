import sys; sys.path.insert(0, 'work/calib_physics_ml'); from s02_p1 import *
out = []
for dn in 'DN':
    d = cal(dn, CB + FB + ['n_sum', 'frp_sum', 'a_n', 'a_frp']); t = test(dn, CB + FB + ['n_sum', 'frp_sum', 'a_n', 'a_frp'])
    for ex in ('SHAF', 'BOAS', 'SEAS'):
        tr = d[d.region != ex]; te = t[t.region == ex]
        for var, xc, yc, raw in (('n', CB, 'a_n', 'n_sum'), ('frp', FB, 'a_frp', 'frp_sum')):
            w = fit_pois(tr[xc].values, tr[yc].values); k = tr[yc].sum() / tr[raw].sum()
            out.append(dict(region=ex, var=var, dn=dn, P1_global_loro=(te[xc].values @ w).sum() / te[yc].sum() - 1,
                            M1_ratio_loro=k * te[raw].sum() / te[yc].sum() - 1))
o = pd.DataFrame(out).round(3); l = pd.read_csv(f'{W}/loro.csv').rename(columns={'bias': 'P3_lgbm_loro'}).drop_duplicates(['region', 'var', 'dn'], keep='last')
o = o.merge(l, on=['region', 'var', 'dn']); o['P3_lgbm_loro'] = o.P3_lgbm_loro.round(3); print(o.to_string()); o.to_csv(f'{R}/loro_comparison.csv', index=False)
