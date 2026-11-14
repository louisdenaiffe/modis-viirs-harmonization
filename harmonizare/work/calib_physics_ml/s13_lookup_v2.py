# accuracy lookup v2 (masked data, production recipe v2), bins on PREDICTED value, adds RMS and day+night ALL
import pandas as pd, numpy as np
W = 'work/calib_physics_ml'
d = pd.concat([pd.read_parquet(f'{W}/prod_{y}.parquet') for y in range(2018, 2022)], ignore_index=True)
BIN = {'n': [1, 10, 100, 1000, 10000, np.inf], 'frp': [1e-9, 1e2, 1e3, 1e4, 1e5, np.inf]}
LAB = {'n': ['1-9', '10-99', '100-999', '1000-9999', '>=10000'], 'frp': ['0-10^2', '10^2-10^3', '10^3-10^4', '10^4-10^5', '>=10^5']}
V = ['pred_n', 'pred_frp', 'obs_n', 'obs_frp']; rows = []
for s in (0.25, 0.5, 1, 2, 5):
    k = int(round(s / 0.25)); x0 = d.assign(bx=d.ix // k, by=d.iy // k)
    for agg, keys in (('monthly', ['year', 'month']), ('annual', ['year'])):
        g = x0.groupby(['bx', 'by', 'daynight'] + keys)[V].sum().reset_index()
        ga = g.groupby(['bx', 'by'] + keys)[V].sum().reset_index().assign(daynight='ALL'); g = pd.concat([g, ga])
        for dn in ('D', 'N', 'ALL'):
            x = g[g.daynight == dn]
            for var in ('n', 'frp'):
                o, p = x[f'obs_{var}'].values, x[f'pred_{var}'].values; b = np.digitize(p, BIN[var]) - 1
                for i, lab in enumerate(LAB[var]):
                    m = b == i; nb = int(m.sum())
                    if nb < 10: continue
                    r = np.divide(p[m], o[m], out=np.full(nb, 99.0), where=o[m] > 0); e = np.abs(r - 1)
                    rows.append(dict(agg=agg, scale_deg=s, daynight=dn, var=var, activity_bin=lab, n_block_months=nb,
                                     median_abs_pct_err=np.median(np.clip(e, 0, 3)) * 100, rms_pct_err=np.sqrt(np.mean(np.clip(r - 1, -3, 3) ** 2)) * 100,
                                     p10_ratio=np.percentile(r, 10), p90_ratio=np.percentile(r, 90),
                                     share_within_20pct=(e <= .2).mean(), share_within_50pct=(e <= .5).mean()))
t = pd.DataFrame(rows); t['p90_ratio'] = t.p90_ratio.where(t.p90_ratio < 99, np.inf); t = t.round(3)
t.to_csv('rezultate/calib_physics_ml/accuracy_modis_scale.csv', index=False); print(len(t))
pd.set_option('display.width', 250)
for agg in ('monthly', 'annual'):
    for var in ('n', 'frp'):
        q = t[(t['agg'] == agg) & (t['var'] == var)]
        print(f'== {agg} {var}: median%/rms%/within20 at scales 0.25 | 1 | 5')
        for dn in ('D', 'N', 'ALL'):
            for lab in LAB[var]:
                s = ''
                for sc in (0.25, 1, 5):
                    r = q[(q.daynight == dn) & (q.activity_bin == lab) & (q.scale_deg == sc)]
                    s += ' | ' + (f'{r.median_abs_pct_err.iloc[0]:.0f}/{r.rms_pct_err.iloc[0]:.0f}/{r.share_within_20pct.iloc[0]:.2f} n={r.n_block_months.iloc[0]}' if len(r) else '-')
                print(dn.ljust(3), lab.ljust(10), s)
