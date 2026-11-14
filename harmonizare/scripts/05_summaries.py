"""05_summaries.py — regional/global tables, independent validation and the before/after figure from the final record.
Run from project folder: python3 harmonizare/scripts/05_summaries.py   (about 40 s)"""
import duckdb, pandas as pd, numpy as np, sys, os, glob, importlib.util
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
R = 'harmonizare'; OUT = f'{R}/rezultate/final'
sys.path.insert(0, f'{R}/scripts'); import eval_common as ec
s = importlib.util.spec_from_file_location('am_r', f'{R}/rezultate/calib_ratio/apply_model.py'); am_r = importlib.util.module_from_spec(s); s.loader.exec_module(am_r)
con = duckdb.connect(); con.execute("SET memory_limit='700MB'; SET threads=2")
cells = pd.DataFrame({'ix': np.repeat(np.arange(1440), 720), 'iy': np.tile(np.arange(720), 1440)})
cells['region'] = ec.region_of(cells.ix.values, cells.iy.values).astype(str); con.register('cells', cells)
K = ['region', 'daynight', 'year', 'month']
raw = con.execute(f"""SELECT satellite, region, daynight, year, month, sum(n_sum) n, sum(frp_sum) frp
  FROM read_parquet('{R}/data/grid/monthly_025/*.parquet') JOIN cells USING (ix, iy) WHERE year BETWEEN 2000 AND 2025 GROUP BY ALL""").df()
fin = con.execute(f"""SELECT region, daynight, year, month, sum(n_eq) n_eq, sum(frp_eq) frp_eq, sum(lo_n) lo_n, sum(hi_n) hi_n,
  sum(lo_frp) lo_frp, sum(hi_frp) hi_frp, any_value(source) AS source, any_value(flag) AS flag
  FROM read_parquet('{OUT}/parts/final_*.parquet') JOIN cells USING (ix, iy) GROUP BY ALL""").df()
veq = pd.concat([pd.read_csv(f) for f in glob.glob(f'{OUT}/parts/viirs_eq_region_*.csv')]).rename(
    columns={'n_eq': 'viirs_eq_n', 'frp_eq': 'viirs_eq_frp', 'n_sum': 'snpp_raw_n', 'frp_sum': 'snpp_raw_frp'})
w = raw.pivot_table(index=K, columns='satellite', values=['n', 'frp'], aggfunc='sum')
w.columns = [f'{s.lower()}_{v}' for v, s in w.columns]; w = w.reset_index()
d = fin.merge(w, on=K, how='outer').merge(veq, on=K, how='outer')
# regional intervals: conversion uncertainty for VIIRS months (region-month level), measurement itself for Aqua months
for var in ('n', 'frp'):
    for dn in 'DN':
        m = (d.source == 'viirs_harmonized') & (d.daynight == dn)
        lo, hi = am_r.regional_interval(d.loc[m, f'{var}_eq'].fillna(0), var, dn); d.loc[m, f'lo_{var}'] = lo; d.loc[m, f'hi_{var}'] = hi
num = [c for c in d.columns if c not in K + ['source', 'flag']]
def add(df, **kw):
    g = df.groupby([k for k in K if k not in kw], dropna=False).agg({**{c: 'sum' for c in num}, 'source': 'first', 'flag': 'first'}).reset_index()
    return g.assign(**kw)
d[num] = d[num].fillna(0)
allr = pd.concat([d, add(d[d.region != 'OTHR'].assign(region='x'), region='GLOBAL')], ignore_index=True)
allr = pd.concat([allr, add(allr, daynight='ALL')], ignore_index=True)
allr['naive_n'] = allr.terra_n + allr.aqua_n + allr.snpp_raw_n; allr['naive_frp'] = allr.terra_frp + allr.aqua_frp + allr.snpp_raw_frp
# anomaly rank: percentile of this month among the same calendar month, 2003-2025
ok = allr.year >= 2003
allr.loc[ok, 'pct_rank_n'] = allr[ok].groupby(['region', 'daynight', 'month']).n_eq.rank(pct=True)
allr.loc[ok, 'pct_rank_frp'] = allr[ok].groupby(['region', 'daynight', 'month']).frp_eq.rank(pct=True)
allr = allr.sort_values(K).round(3); allr.to_csv(f'{OUT}/region_month.csv', index=False)
# ---- validation: VIIRS-equivalent vs real Aqua, months where both satellites were healthy
comp = pd.read_csv(f'{R}/rezultate/qc_stability/completeness_monthly.csv')
bad = set(map(tuple, comp[(comp.flag_month != 'ok') & comp.satellite.isin(['Aqua', 'SNPP'])][['year', 'month']].values))
v = allr[(allr.daynight != 'ALL') & (allr.region != 'OTHR') & ~allr[['year', 'month']].apply(tuple, axis=1).isin(bad)]
rows = []
for name, (y0, y1) in {'calibration 2012-2017': (2012, 2017), 'test 2018-2021': (2018, 2021), 'drift era 2022-2023': (2022, 2023), 'drift era 2024-2025': (2024, 2025)}.items():
    p = v[v.year.between(y0, y1)]
    for (reg, dn), g in p.groupby(['region', 'daynight']):
        if g.aqua_n.sum() < 500: continue
        rows.append(dict(period=name, region=reg, daynight=dn, months=len(g), aqua_n=g.aqua_n.sum(),
                         raw_viirs_bias_n=g.snpp_raw_n.sum() / g.aqua_n.sum() - 1, harm_bias_n=g.viirs_eq_n.sum() / g.aqua_n.sum() - 1,
                         harm_nmae_n=(g.viirs_eq_n - g.aqua_n).abs().sum() / g.aqua_n.sum(),
                         raw_viirs_bias_frp=g.snpp_raw_frp.sum() / g.aqua_frp.sum() - 1, harm_bias_frp=g.viirs_eq_frp.sum() / g.aqua_frp.sum() - 1,
                         harm_nmae_frp=(g.viirs_eq_frp - g.aqua_frp).abs().sum() / g.aqua_frp.sum(), r_n=np.corrcoef(g.viirs_eq_n, g.aqua_n)[0, 1]))
val = pd.DataFrame(rows).round(4); val.to_csv(f'{OUT}/validation_by_region.csv', index=False)
print(val[val.region == 'GLOBAL'].to_string(index=False))
reg = val[val.region != 'GLOBAL']
print(reg.groupby(['period', 'daynight']).agg(med_abs_bias_n=('harm_bias_n', lambda x: x.abs().median()), max_abs_bias_n=('harm_bias_n', lambda x: x.abs().max()),
      med_abs_bias_frp=('harm_bias_frp', lambda x: x.abs().median()), max_abs_bias_frp=('harm_bias_frp', lambda x: x.abs().max())).round(3).to_string())
# ---- annual global table + figure
g = allr[(allr.region == 'GLOBAL') & (allr.daynight == 'ALL')]
ann = g.groupby('year')[['naive_n', 'n_eq', 'aqua_n', 'terra_n', 'snpp_raw_n', 'viirs_eq_n', 'frp_eq', 'naive_frp']].sum().round(0)
ann.to_csv(f'{OUT}/annual_global.csv'); print(ann[['naive_n', 'n_eq', 'aqua_n', 'viirs_eq_n']].to_string())
fig, ax = plt.subplots(2, 2, figsize=(14, 9))
a = ax[0, 0]; yrs = ann.index[(ann.index >= 2001)]
a.plot(yrs, ann.loc[yrs, 'naive_n'] / 1e6, 'o-', color='#c0392b', label='Naive: all MODIS + all VIIRS points added up')
a.plot(yrs, ann.loc[yrs, 'n_eq'] / 1e6, 'o-', color='#1f4e79', label='Harmonized (Aqua-equivalent)')
a.axvline(2011.5, color='grey', ls=':'); a.axvline(2021.5, color='grey', ls=':'); a.set_yscale('log'); a.set_ylabel('fire detections per year (millions, log)')
a.set_title('Global: naive concatenation vs harmonized record'); a.legend(fontsize=8)
a = ax[0, 1]; gm = g[(g.year >= 2003)].copy(); gm['t'] = gm.year + (gm.month - 0.5) / 12
a.fill_between(gm.t, gm.lo_n / 1e3, gm.hi_n / 1e3, color='#1f4e79', alpha=0.25); a.plot(gm.t, gm.n_eq / 1e3, color='#1f4e79', lw=0.9, label='Harmonized')
ov = gm[gm.year.between(2012, 2021)]; a.plot(ov.t, ov.viirs_eq_n / 1e3, color='#e67e22', lw=0.8, alpha=0.9, label='VIIRS converted (overlap, for checking)')
a.axvline(2022, color='grey', ls=':'); a.set_ylabel('detections per month (thousands)'); a.set_title('Global monthly record, 2003-2025 (VIIRS-based from 2022)'); a.legend(fontsize=8)
a = ax[1, 0]; t = val[(val.period == 'test 2018-2021') & (val.daynight == 'D') & (val.region != 'GLOBAL')].sort_values('region')
x = np.arange(len(t)); a.bar(x - 0.2, t.harm_bias_n * 100, 0.4, color='#1f4e79', label='counts'); a.bar(x + 0.2, t.harm_bias_frp * 100, 0.4, color='#e67e22', label='FRP')
a.set_xticks(x); a.set_xticklabels(t.region, rotation=60); a.axhline(0, color='k', lw=0.5); a.set_ylabel('% error vs real Aqua'); a.set_title('Held-out years 2018-2021, daytime: harmonized VIIRS vs real Aqua'); a.legend(fontsize=8)
a = ax[1, 1]; tr = v[(v.region == 'GLOBAL') & (v.daynight == 'D')].groupby('year')[['terra_n', 'aqua_n', 'viirs_eq_n']].sum(); tr = tr[tr.index >= 2012]
a.plot(tr.index, tr.terra_n / tr.viirs_eq_n / (tr.terra_n / tr.viirs_eq_n).loc[2012:2019].mean(), 'o-', color='#8e44ad', label='Terra / harmonized VIIRS')
a.plot(tr.index, tr.aqua_n / tr.viirs_eq_n / (tr.aqua_n / tr.viirs_eq_n).loc[2012:2019].mean(), 'o-', color='#27ae60', label='Aqua / harmonized VIIRS')
a.axhline(1, color='k', lw=0.5); a.set_ylabel('ratio relative to 2012-2019'); a.set_title('Why MODIS cannot simply continue: orbit drift (daytime counts, healthy months only)'); a.legend(fontsize=8)
plt.tight_layout(); plt.savefig(f'{OUT}/fig_harmonization_summary.png', dpi=130)
print('naive step 2011->2012: x%.2f | harmonized: x%.2f' % (ann.naive_n[2012] / ann.naive_n[2011], ann.n_eq[2012] / ann.n_eq[2011]))
print('harmonized 2021->2022 (Aqua -> VIIRS-based): x%.2f' % (ann.n_eq[2022] / ann.n_eq[2021]))
print('drift ratios (terra, aqua vs VIIRS-eq, rel 2012-19):'); print((tr.terra_n / tr.viirs_eq_n / (tr.terra_n / tr.viirs_eq_n).loc[2012:2019].mean()).round(3).to_dict()); print((tr.aqua_n / tr.viirs_eq_n / (tr.aqua_n / tr.viirs_eq_n).loc[2012:2019].mean()).round(3).to_dict())
