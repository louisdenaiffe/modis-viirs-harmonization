# accuracy vs spatial scale x activity, production recipe on 2018-2021 test
import pandas as pd, numpy as np
W = 'work/calib_physics_ml'
d = pd.concat([pd.read_parquet(f'{W}/prod_{y}.parquet') for y in range(2018, 2022)], ignore_index=True)
BIN = {'n': [1, 10, 100, 1000, np.inf], 'frp': [10, 100, 1000, 10000, np.inf]}
LAB = {'n': ['1-9', '10-99', '100-999', '>=1000'], 'frp': ['10-99MW', '100-999MW', '1e3-1e4MW', '>=1e4MW']}
rows = []
for s in (0.25, 0.5, 1, 2, 5, 10):
    k = int(round(s / 0.25)); bx, by = d.ix // k, d.iy // k
    for agg, keys in (('monthly', ['year', 'month']), ('annual', ['year'])):
        g = d.assign(bx=bx, by=by).groupby(['bx', 'by', 'daynight'] + keys)[['pred_n', 'pred_frp', 'obs_n', 'obs_frp']].sum().reset_index()
        for var in ('n', 'frp'):
            for dn in 'DN':
                x = g[g.daynight == dn]; o, p = x[f'obs_{var}'].values, x[f'pred_{var}'].values
                for on, v in (('obs', o), ('pred', p)):
                    b = np.digitize(v, BIN[var]) - 1
                    for i, lab in enumerate(LAB[var]):
                        m = b == i
                        if m.sum() < 20: continue
                        r = np.divide(p[m], o[m], out=np.full(m.sum(), 99.0), where=o[m] > 0)
                        e = np.abs(r - 1)
                        rows.append(dict(scale_deg=s, agg=agg, daynight=dn, var=var, bin_on=on, activity_bin=lab, n_blocks=int(m.sum()),
                                         median_abs_pct_err=np.median(e) * 100, p10_ratio=np.percentile(r, 10), p90_ratio=np.percentile(r, 90),
                                         share_within_20pct=(e <= 0.2).mean(), share_within_50pct=(e <= 0.5).mean(),
                                         pooled_bias_pct=(p[m].sum() / o[m].sum() - 1) * 100))
t = pd.DataFrame(rows).round(3); t['p90_ratio'] = t.p90_ratio.where(t.p90_ratio < 99, np.inf); t.to_csv(f'{W}/scale_all.csv', index=False)
app = t[t.bin_on == 'pred'].drop(columns='bin_on'); app.to_csv('rezultate/calib_physics_ml/accuracy_by_scale.csv', index=False)
pd.set_option('display.width', 250)
for agg in ('monthly', 'annual'):
    for var in ('n', 'frp'):
        q = t[(t['agg'] == agg) & (t['var'] == var)]
        print(f'== {agg} {var}  cells: med%err / p10-p90 / within20 (obs-binned | pred-binned)')
        for dn in 'DN':
            for lab in LAB[var]:
                s = ''
                for sc in (0.25, 0.5, 1, 2, 5, 10):
                    z = [q[(q.daynight == dn) & (q.activity_bin == lab) & (q.scale_deg == sc) & (q.bin_on == on)] for on in ('obs', 'pred')]
                    s += ' | ' + ' '.join(f'{r.median_abs_pct_err.iloc[0]:.0f}/{r.p10_ratio.iloc[0]:.2f}-{r.p90_ratio.iloc[0]:.2f}/{r.share_within_20pct.iloc[0]:.2f}' if len(r) else '-' for r in z)
                print(dn, lab.ljust(10), s)
