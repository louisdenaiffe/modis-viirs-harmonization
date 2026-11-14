"""Drift impact: yearly ratio index of satellite pairs vs their 2012-2019 baseline, global and per eval region.
index(y) = sum_m A[y,m] / sum_m k_m * B[y,m]  over valid months, k_m = sum A / sum B for calendar month m over 2012-2019
(seasonally robust: a missing month does not shift the index). Valid month = flag_month 'ok' for BOTH satellites."""
import pandas as pd, numpy as np, os
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
R = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')); OUT = f'{R}/rezultate/qc_stability'
rm = pd.read_parquet(f'{R}/work/qc_stability/regional_monthly.parquet')
rm = rm.groupby(['satellite', 'year', 'month', 'daynight', 'region'], as_index=False)[['n_sum', 'frp_sum']].sum()
g = rm.groupby(['satellite', 'year', 'month', 'daynight'], as_index=False)[['n_sum', 'frp_sum']].sum(); g['region'] = 'GLOBAL'
rm = pd.concat([rm, g])
comp = pd.read_csv(f'{OUT}/completeness_monthly.csv')
okm = comp[comp.flag_month == 'ok'][['satellite', 'daynight', 'year', 'month']]
rows = []
for A, B in [('Aqua', 'SNPP'), ('Terra', 'Aqua'), ('Terra', 'SNPP')]:
    a = rm[rm.satellite == A].merge(okm[okm.satellite == A].drop(columns='satellite'))
    b = rm[rm.satellite == B].merge(okm[okm.satellite == B].drop(columns='satellite'))
    m = a.drop(columns='satellite').merge(b.drop(columns='satellite'), on=['year', 'month', 'daynight', 'region'], suffixes=('_a', '_b'))
    m = m[m.year.between(2012, 2025)]
    for var in ('n_sum', 'frp_sum'):
        base = m[m.year <= 2019].groupby(['region', 'daynight', 'month'])[[f'{var}_a', f'{var}_b']].sum()
        k = (base[f'{var}_a'] / base[f'{var}_b']).replace([np.inf], np.nan).rename('k').reset_index()
        x = m.merge(k, on=['region', 'daynight', 'month']); x['exp'] = x.k * x[f'{var}_b']
        y = x.groupby(['region', 'daynight', 'year']).agg(a=(f'{var}_a', 'sum'), b=(f'{var}_b', 'sum'), exp=('exp', 'sum'),
                                                         months=('month', 'size')).reset_index()
        y['ratio'] = y.a / y.b; y['index_vs_2012_2019'] = y.a / y.exp; y['pct_change'] = 100 * (y.index_vs_2012_2019 - 1)
        y['pair'] = f'{A}/{B}'; y['var'] = var; rows.append(y)
res = pd.concat(rows)[['pair', 'var', 'daynight', 'region', 'year', 'months', 'a', 'b', 'ratio', 'index_vs_2012_2019', 'pct_change']]
res.round(4).to_csv(f'{OUT}/ratio_by_year.csv', index=False)
# figure: global
fig, ax = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
for i, var in enumerate(('n_sum', 'frp_sum')):
    for j, dn in enumerate('DN'):
        for p, c in zip(['Aqua/SNPP', 'Terra/Aqua', 'Terra/SNPP'], ['#2a6fdb', '#d9822b', '#6b8e23']):
            s = res[(res.pair == p) & (res['var'] == var) & (res.daynight == dn) & (res.region == 'GLOBAL')]
            ax[i, j].plot(s.year, s['pct_change'], 'o-', color=c, label=p)
        ax[i, j].axhline(0, color='grey', lw=.8); ax[i, j].axvspan(2021.5, 2025.5, color='grey', alpha=.1)
        ax[i, j].set_title(f"{'counts' if var == 'n_sum' else 'FRP'} — {'day' if dn == 'D' else 'night'} (global)")
        ax[i, j].set_ylabel('% vs 2012-2019 ratio')
ax[0, 0].legend(); fig.suptitle('Ratio drift between satellites (shaded: orbit-drift years)'); fig.tight_layout()
fig.savefig(f'{OUT}/fig_ratio_drift.png', dpi=110)
pd.set_option('display.width', 250)
G = res[res.region == 'GLOBAL']
print(G.pivot_table(index='year', columns=['pair', 'var', 'daynight'], values='pct_change').round(1).to_string())
