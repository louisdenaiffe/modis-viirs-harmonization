"""Terra -> Aqua-equivalent back-fill factors for 2000-11..2002-06.
f[region, calendar month, daynight] = sum Aqua / sum Terra (monthly sums, n_sum and frp_sum) over 2003-2012, months 'ok' for both.
Validation 2013-2019: pred Aqua = f * Terra per region-month; bias = sum pred / sum obs - 1, nMAE = sum|pred-obs| / sum obs.
Baseline for comparison: one global factor per daynight."""
import pandas as pd, numpy as np, os
R = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')); OUT = f'{R}/rezultate/qc_stability'
rm = pd.read_parquet(f'{R}/work/qc_stability/regional_monthly.parquet')
rm = rm.groupby(['satellite', 'year', 'month', 'daynight', 'region'], as_index=False)[['n_sum', 'frp_sum']].sum()
comp = pd.read_csv(f'{OUT}/completeness_monthly.csv'); okm = comp[comp.flag_month == 'ok'][['satellite', 'daynight', 'year', 'month']]
a = rm[rm.satellite == 'Aqua'].merge(okm[okm.satellite == 'Aqua'].drop(columns='satellite')).drop(columns='satellite')
t = rm[rm.satellite == 'Terra'].merge(okm[okm.satellite == 'Terra'].drop(columns='satellite')).drop(columns='satellite')
m = a.merge(t, on=['year', 'month', 'daynight', 'region'], how='outer', suffixes=('_a', '_t'))
okboth = okm[okm.satellite == 'Aqua'].drop(columns='satellite').merge(okm[okm.satellite == 'Terra'].drop(columns='satellite'))
m = m.merge(okboth, on=['daynight', 'year', 'month']).fillna(0)
fit, val = m[m.year.between(2003, 2012)], m[m.year.between(2013, 2019)]
F = fit.groupby(['region', 'month', 'daynight']).agg(aqua_n=('n_sum_a', 'sum'), terra_n=('n_sum_t', 'sum'),
                                                     aqua_frp=('frp_sum_a', 'sum'), terra_frp=('frp_sum_t', 'sum'), months=('year', 'size')).reset_index()
F['f_n'] = F.aqua_n / F.terra_n; F['f_frp'] = F.aqua_frp / F.terra_frp
# fallback when Terra sum is tiny (< 50 detections over 10 years): region x daynight annual factor
RA = fit.groupby(['region', 'daynight'])[['n_sum_a', 'n_sum_t', 'frp_sum_a', 'frp_sum_t']].sum()
F = F.merge((RA.n_sum_a / RA.n_sum_t).rename('fr_n').reset_index()).merge((RA.frp_sum_a / RA.frp_sum_t).rename('fr_frp').reset_index())
F['fallback'] = F.terra_n < 50
F.loc[F.fallback, 'f_n'] = F.fr_n; F.loc[F.fallback, 'f_frp'] = F.fr_frp
F = F.replace([np.inf, -np.inf], np.nan)
# interannual spread of the monthly factor (how stable is it?)
yr = fit.groupby(['region', 'month', 'daynight', 'year'])[['n_sum_a', 'n_sum_t']].sum()
cv = (yr.n_sum_a / yr.n_sum_t).replace([np.inf], np.nan).groupby(level=[0, 1, 2]).agg(lambda s: s.std() / s.mean()).rename('f_n_interannual_cv')
F = F.merge(cv.reset_index(), how='left')
F.drop(columns=['fr_n', 'fr_frp']).round(4).to_csv(f'{OUT}/terra_to_aqua_factors.csv', index=False)
G = fit.groupby('daynight')[['n_sum_a', 'n_sum_t', 'frp_sum_a', 'frp_sum_t']].sum()
v = val.merge(F[['region', 'month', 'daynight', 'f_n', 'f_frp']], how='left').fillna({'f_n': 0, 'f_frp': 0})
v['g_n'] = v.daynight.map(G.n_sum_a / G.n_sum_t); v['g_frp'] = v.daynight.map(G.frp_sum_a / G.frp_sum_t)
rows = []
for var, obs, ter in (('n', 'n_sum_a', 'n_sum_t'), ('frp', 'frp_sum_a', 'frp_sum_t')):
    for model, fc in (('region_month', f'f_{var}'), ('global', f'g_{var}')):
        v['pred'] = v[fc] * v[ter]
        for dn in 'DN':
            d = v[v.daynight == dn]
            for reg, g in list(d.groupby('region')) + [('GLOBAL', d.groupby(['year', 'month'], as_index=False)[[obs, 'pred']].sum())]:
                so = g[obs].sum()
                if so <= 0: continue
                rows.append(dict(var=var, model=model, daynight=dn, region=reg, obs_total=so, bias=g.pred.sum() / so - 1,
                                 nmae=(g.pred - g[obs]).abs().sum() / so, r=np.corrcoef(g[obs], g.pred)[0, 1], months=len(g)))
V = pd.DataFrame(rows).round(4); V.to_csv(f'{OUT}/terra_to_aqua_validation.csv', index=False)
main = V[(V.region != 'OTHR')]
s = main[main.region != 'GLOBAL'].groupby(['var', 'daynight', 'model']).agg(med_abs_bias=('bias', lambda x: x.abs().median()),
        max_abs_bias=('bias', lambda x: x.abs().max()), med_nmae=('nmae', 'median'), med_r=('r', 'median'))
print(s.round(3).to_string())
print(main[main.region == 'GLOBAL'].to_string())
print(V[(V.model == 'region_month') & (V['var'] == 'n') & (V.daynight == 'D')].sort_values('obs_total', ascending=False).to_string())
print(V[(V.model == 'region_month') & (V['var'] == 'frp') & (V.daynight == 'D')].sort_values('obs_total', ascending=False)[['region','bias','nmae','r']].to_string())
c = comp[(comp.satellite == 'Terra') & ((comp.year * 12 + comp.month).between(2000 * 12 + 11, 2002 * 12 + 6))]
print(c[c.flag_month != 'ok'].to_string()); print('terra-era months', len(c) // 2)
