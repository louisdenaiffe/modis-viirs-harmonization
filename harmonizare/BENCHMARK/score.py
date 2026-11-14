"""score.py — one scoring code for every harmonization model (VIIRS-scale back-cast test).
Truth : real S-NPP VIIRS monthly values per 0.25 deg cell, FIRMS type 0, confidence not low  (truth_and_ours_2018_2023.parquet).
Usage : python3 score.py --name ours                                   # scores our model (columns pred_n / pred_frp in the truth file)
        python3 score.py --name other --pred other_pred.parquet        # scores another model
        options: --years 2018-2021   --truth plain|masked   --countries Brazil,Greece,...   --out scores_<name>.csv
Prediction file schema (parquet or csv): ix, iy, year, month, daynight ('D' or 'N'), pred_n, pred_frp   (missing rows = 0)
        ix = floor((lon + 180) / 0.25), iy = floor((lat + 90) / 0.25); VIIRS-scale monthly prediction made from MODIS only.
Metrics never let + and - errors cancel except 'bias': nmae = sum|p-o| / sum(o); nrmse = RMSE / mean(o), at unit-month level."""
import argparse, numpy as np, pandas as pd, os
ap = argparse.ArgumentParser(); ap.add_argument('--name', required=True); ap.add_argument('--pred'); ap.add_argument('--years', default='2018-2021')
ap.add_argument('--truth', default='plain'); ap.add_argument('--countries'); ap.add_argument('--out'); a = ap.parse_args()
H = os.path.dirname(os.path.abspath(__file__)); K = ['ix', 'iy', 'year', 'month', 'daynight']
t = pd.read_parquet(f'{H}/truth_and_ours_2018_2023.parquet'); y0, y1 = map(int, a.years.split('-'))
t = t[t.month_ok & t.year.between(y0, y1)].copy()
t['obs_n'] = t.viirs_n if a.truth == 'plain' else t.viirs_n_masked; t['obs_frp'] = t.viirs_frp if a.truth == 'plain' else t.viirs_frp_masked
if a.pred:
    p = pd.read_parquet(a.pred) if a.pred.endswith('.parquet') else pd.read_csv(a.pred)
    p = p[K + [c for c in ('pred_n', 'pred_frp') if c in p]].groupby(K, as_index=False).sum()
    meta = t[K + ['obs_n', 'obs_frp', 'country', 'region']]
    t = meta.merge(p, on=K, how='outer')
    lost = t.country.isna()                                  # predictions in cells/months with no truth row = truth is zero there
    if lost.any():
        cc = meta.drop_duplicates(['ix', 'iy']).set_index(['ix', 'iy'])[['country', 'region']]
        j = t.loc[lost, ['ix', 'iy']].join(cc, on=['ix', 'iy']); t.loc[lost, 'country'] = j.country.values; t.loc[lost, 'region'] = j.region.values
    t = t[t.year.between(y0, y1)]; t[['obs_n', 'obs_frp']] = t[['obs_n', 'obs_frp']].fillna(0); t['country'] = t.country.fillna('unassigned'); t['region'] = t.region.fillna('OTHR')
for c in ('pred_n', 'pred_frp'):
    if c not in t: t[c] = np.nan
    t[c] = t[c].fillna(0)
if a.countries: t = t[t.country.isin(a.countries.split(','))]
t['bx'] = t.ix // 4; t['by'] = t.iy // 4
tot = t.groupby([c for c in t.columns if c not in ('daynight', 'obs_n', 'obs_frp', 'pred_n', 'pred_frp', 'viirs_n', 'viirs_frp', 'viirs_n_masked', 'viirs_frp_masked', 'aqua_n', 'aqua_frp', 'month_ok')], as_index=False)[['obs_n', 'obs_frp', 'pred_n', 'pred_frp']].sum().assign(daynight='ALL')
t = pd.concat([t[tot.columns], tot], ignore_index=True)
LEVELS = {'global': [], 'region': ['region'], 'country': ['country'], 'block_1deg': ['bx', 'by'], 'cell_0.25deg': ['ix', 'iy']}
rows = []
for dn in ('D', 'N', 'ALL'):
    x = t[t.daynight == dn]
    for var in ('n', 'frp'):
        o, p = f'obs_{var}', f'pred_{var}'
        for lev, keys in LEVELS.items():
            g = x.groupby(keys + ['year', 'month'], as_index=False)[[o, p]].sum()
            r = dict(model=a.name, years=a.years, truth=a.truth, daynight=dn, var=var, level=lev, n_unit_months=len(g),
                     bias=g[p].sum() / g[o].sum() - 1, nmae=(g[p] - g[o]).abs().sum() / g[o].sum(), nrmse=np.sqrt(((g[p] - g[o]) ** 2).mean()) / g[o].mean())
            if lev in ('region', 'country'):                  # per-unit view: how many units are well served
                u = g.groupby(keys).apply(lambda d: pd.Series(dict(o=d[o].sum(), b=d[p].sum() / max(d[o].sum(), 1e-9) - 1, e=(d[p] - d[o]).abs().sum() / max(d[o].sum(), 1e-9),
                        rho=d[[o, p]].corr(method='spearman').iloc[0, 1] if len(d) > 5 else np.nan)))
                u = u[u.o >= (200 if var == 'n' else 2000)]
                r.update(units=len(u), med_abs_bias=u.b.abs().median(), share_units_within_20pct=(u.b.abs() <= .2).mean(), worst_abs_bias=u.b.abs().max(),
                         med_unit_nmae=u.e.median(), med_spearman=u.rho.median())
            rows.append(r)
S = pd.DataFrame(rows).round(4); out = a.out or f'{H}/scores_{a.name}.csv'; S.to_csv(out, index=False)
print(S[S.level.isin(['global', 'region', 'country'])][['daynight', 'var', 'level', 'bias', 'nmae', 'nrmse', 'med_abs_bias', 'share_units_within_20pct', 'worst_abs_bias', 'med_unit_nmae', 'med_spearman']].to_string(index=False))
print(S[S.level.isin(['block_1deg', 'cell_0.25deg'])][['daynight', 'var', 'level', 'bias', 'nmae', 'nrmse']].to_string(index=False)); print('saved', out)
