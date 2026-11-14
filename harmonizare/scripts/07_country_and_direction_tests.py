"""07_country_and_direction_tests.py — two checks on held-out years 2018-2021 (Aug-Sep 2020 excluded).
A) Per-country accuracy of the production conversion (VIIRS -> Aqua-equivalent) vs real Aqua  -> rezultate/final/validation_by_country.csv
B) The opposite direction (Aqua -> VIIRS scale) with the same kind of factors, vs real VIIRS       -> rezultate/final/direction_test.csv
Run from project folder: python3 harmonizare/scripts/07_country_and_direction_tests.py"""
import duckdb, pandas as pd, numpy as np, sys, importlib.util
R = 'harmonizare'; OUT = f'{R}/rezultate/final'
sys.path.insert(0, f'{R}/scripts'); import eval_common as ec
def mod(path, name):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
am1 = mod(f'{R}/rezultate/calib_ratio/apply_model.py', 'am1'); am2 = mod(f'{R}/rezultate/calib_ratio/apply_model_v2.py', 'am2'); amp = mod(f'{R}/rezultate/calib_physics_ml/apply_model.py', 'amp')
con = duckdb.connect(); con.execute("SET memory_limit='900MB'; SET threads=2")
K = ['ix', 'iy', 'year', 'month', 'daynight']
def drop_excl(d):
    for y, m in ec.EXCLUDE: d = d[~((d.year == y) & (d.month == m))]
    return d
# ---------- A) per country
v = con.execute(f"SELECT * FROM read_parquet('{ec.MONTHLY}') WHERE satellite='SNPP' AND {ec.ym_filter(ec.TEST)}").df()
p = am2.predict(v, interval=False); pn, pf = amp.predict(v, counts='p1'); night = (v.daynight == 'N').values
v['pred_n'] = np.where(night, pn, p.pred_n.values); v['pred_frp'] = np.where(night, pf, p.pred_frp.values)
a = ec.load('Aqua', ec.TEST).rename(columns={'n_sum': 'obs_n', 'frp_sum': 'obs_frp'})
d = drop_excl(a.merge(v[K + ['pred_n', 'pred_frp', 'n_sum', 'frp_sum']], on=K, how='outer').fillna(0))
cc = pd.read_parquet(f'{R}/rezultate/events_countries/cell_country.parquet')[['ix', 'iy', 'country']]
d = d.merge(cc, on=['ix', 'iy'], how='left'); d['country'] = d.country.fillna('unassigned')
cm = d.groupby(['country', 'daynight', 'year', 'month'])[['obs_n', 'pred_n', 'obs_frp', 'pred_frp', 'n_sum']].sum().reset_index()
rows = []
for (c, dn), g in cm.groupby(['country', 'daynight']):
    so = g.obs_n.sum()
    if so < 200: continue
    rows.append(dict(country=c, daynight=dn, aqua_detections=so, aqua_per_month=so / 44, raw_viirs_over_aqua=g.n_sum.sum() / so,
                     bias_n=g.pred_n.sum() / so - 1, nmae_month_n=(g.pred_n - g.obs_n).abs().sum() / so,
                     bias_frp=g.pred_frp.sum() / g.obs_frp.sum() - 1, nmae_month_frp=(g.pred_frp - g.obs_frp).abs().sum() / g.obs_frp.sum(),
                     r_month=np.corrcoef(g.pred_n, g.obs_n)[0, 1]))
C = pd.DataFrame(rows).round(4); C.to_csv(f'{OUT}/validation_by_country.csv', index=False)
for dn in 'DN':
    c = C[C.daynight == dn]; b = c.bias_n.abs()
    print(f"[A] {dn}: {len(c)} countries with >=200 Aqua detections | |bias| counts: median {b.median():.3f}, within 10%: {(b <= .1).mean():.2f}, within 20%: {(b <= .2).mean():.2f}"
          f" | monthly nMAE median {c.nmae_month_n.median():.3f} | FRP |bias| median {c.bias_frp.abs().median():.3f} | monthly corr median {c.r_month.median():.3f}")
    for lab, m in (('>=1000/month', c.aqua_per_month >= 1000), ('100-999', c.aqua_per_month.between(100, 999.99)), ('10-99', c.aqua_per_month.between(10, 99.99)), ('<10', c.aqua_per_month < 10)):
        if m.sum(): print(f"      {lab:13s} n={m.sum():3d} median |bias| {c[m].bias_n.abs().median():.3f}  median monthly nMAE {c[m].nmae_month_n.median():.3f}")
    w = c.sort_values('aqua_detections', ascending=False).head(60); print('      worst of the 60 most fire-active:', w.reindex(w.bias_n.abs().sort_values(ascending=False).index).head(6)[['country', 'bias_n']].round(2).values.tolist())
print(C[C.country.isin(['Romania', 'Italy', 'Greece', 'Brazil', 'Australia', 'Canada', 'Indonesia'])][['country', 'daynight', 'aqua_per_month', 'raw_viirs_over_aqua', 'bias_n', 'nmae_month_n', 'bias_frp']].to_string(index=False))
# ---------- B) opposite direction: Aqua -> VIIRS scale (same B5-type factors, roles swapped; calibration 2012-02..2017-12)
ca, cs = ec.load('Aqua', ec.CAL), ec.load('SNPP', ec.CAL)
cal = ca.merge(cs, on=K, how='outer', suffixes=('_a', '_s')).fillna(0)
cal = cal.rename(columns={'n_sum_s': 'a_n', 'frp_sum_s': 'a_frp', 'n_sum_a': 's_n', 'frp_sum_a': 's_frp'})   # target = VIIRS, input = Aqua
F = am1.fit_factors(cal)
ta = ec.load('Aqua', ec.TEST); ts = ec.load('SNPP', ec.TEST).rename(columns={'n_sum': 'obs_n', 'frp_sum': 'obs_frp'})
pr = am1.predict(ta, F, interval=False)
t = drop_excl(ts.merge(pr[K + ['pred_n', 'pred_frp']], on=K, how='outer').merge(ta.rename(columns={'n_sum': 'aq_n'})[K + ['aq_n']], on=K, how='left').fillna(0))
t['region'] = ec.region_of(t.ix.values, t.iy.values)
rows = []
for dn in 'DN':
    x = t[t.daynight == dn]
    for var in ('n', 'frp'):
        rm = x[x.region != 'OTHR'].groupby(['region', 'year', 'month'])[[f'obs_{var}', f'pred_{var}']].sum().reset_index()
        rb = rm.groupby('region').apply(lambda g: pd.Series(dict(bias=g[f'pred_{var}'].sum() / g[f'obs_{var}'].sum() - 1, nmae=(g[f'pred_{var}'] - g[f'obs_{var}']).abs().sum() / g[f'obs_{var}'].sum())))
        rows.append(dict(direction='Aqua -> VIIRS scale', daynight=dn, var=var, global_bias=x[f'pred_{var}'].sum() / x[f'obs_{var}'].sum() - 1,
                         reg_med_abs_bias=rb.bias.abs().median(), reg_max_abs_bias=rb.bias.abs().max(), reg_med_nmae=rb.nmae.median(),
                         cell_mae_rel=(x[f'pred_{var}'] - x[f'obs_{var}']).abs().sum() / x[f'obs_{var}'].sum()))
    z = x[x.obs_n > 0]; print(f"[B] {dn}: VIIRS-active cell-months with ZERO Aqua detections: {(z.aq_n == 0).mean():.2f} of cell-months, holding {z[z.aq_n == 0].obs_n.sum() / z.obs_n.sum():.2f} of VIIRS detections")
# same relative cell-level error for the production direction, for a like-for-like comparison
for dn in 'DN':
    x = d[d.daynight == dn]
    for var in ('n', 'frp'):
        rows.append(dict(direction='VIIRS -> Aqua scale (production)', daynight=dn, var=var, global_bias=x[f'pred_{var}'].sum() / x[f'obs_{var}'].sum() - 1,
                         cell_mae_rel=(x[f'pred_{var}'] - x[f'obs_{var}']).abs().sum() / x[f'obs_{var}'].sum()))
D = pd.DataFrame(rows).round(4); D.to_csv(f'{OUT}/direction_test.csv', index=False); print(D.to_string(index=False))
