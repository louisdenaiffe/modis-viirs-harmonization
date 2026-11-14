"""Default mask -> rezultate/static_mask/static_mask_001.parquet, cell_static_share.parquet, impact tables.
Run inside harmonizare/work/static_mask:  python3 06_final.py"""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, '../../scripts')
import pandas as pd, numpy as np
import eval_common as ec
M = __import__('04_mask'); c = M.c
OUT = '../../rezultate/static_mask'
CFG = dict(D=16, M=9, Y=2, tmin=3, mflag=6, nsmin=0.9, M2=4, Y2=1, spread=2, buf=1, eruptions=True)
m = M.build(**CFG); assert not m.duplicated(['sx', 'sy']).any()
c.register('mm', m)
c.execute(f"COPY (SELECT sx::INT sx, sy::INT sy, reason::VARCHAR reason FROM mm ORDER BY sx, sy) TO '{OUT}/static_mask_001.parquet' (FORMAT PARQUET)")
print(pd.crosstab(m.reason, m.core, margins=True))
# per 0.25 deg cell x satellite x daynight, 3 years summed: default-filter n/frp total and inside mask
c.execute(f"""COPY (WITH s AS (SELECT s.*, mm.sx IS NOT NULL AS msk FROM 'cells/*.parquet' s LEFT JOIN mm USING (sx, sy))
  SELECT (sx // 25)::SMALLINT ix, (sy // 25)::SMALLINT iy, satellite, 'D' daynight, sum(nD)::INT n_total, sum(nD) FILTER (msk)::INT n_static,
         sum(fD)::FLOAT frp_total, sum(fD) FILTER (msk)::FLOAT frp_static FROM s GROUP BY 1,2,3 HAVING sum(nD) > 0
  UNION ALL
  SELECT (sx // 25)::SMALLINT, (sy // 25)::SMALLINT, satellite, 'N', sum(nN)::INT, sum(nN) FILTER (msk)::INT, sum(fN)::FLOAT, sum(fN) FILTER (msk)::FLOAT
  FROM s GROUP BY 1,2,3 HAVING sum(nN) > 0) TO '{OUT}/_tmp_share.parquet' (FORMAT PARQUET)""")
d = pd.read_parquet(f'{OUT}/_tmp_share.parquet').fillna({'n_static': 0, 'frp_static': 0})
d['n_static'] = d.n_static.astype('int32'); d['static_share_n'] = (d.n_static / d.n_total).astype('float32')
d['static_share_frp'] = (d.frp_static / d.frp_total.where(d.frp_total > 0)).astype('float32')
d['years'] = '2015,2019,2021'
d.to_parquet(f'{OUT}/cell_static_share.parquet', index=False)
import os; os.remove(f'{OUT}/_tmp_share.parquet')
d['region'] = ec.region_of(d.ix.values, d.iy.values)
def summ(g):
    return pd.Series(dict(n_total=g.n_total.sum(), n_static=g.n_static.sum(), pct_n=100 * g.n_static.sum() / g.n_total.sum(),
                          pct_frp=100 * g.frp_static.sum() / g.frp_total.sum()))
reg = d.groupby(['region', 'satellite', 'daynight']).apply(summ).reset_index()
glob = d.groupby(['satellite', 'daynight']).apply(summ).reset_index(); glob['region'] = 'GLOBAL'
imp = pd.concat([glob, reg]); imp.to_csv(f'{OUT}/impact_by_region.csv', index=False, float_format='%.3f')
# SNPP/Aqua ratio before / after
r = imp.pivot_table(index=['region', 'daynight'], columns='satellite', values=['n_total', 'n_static'])
out = pd.DataFrame({'ratio_before': r[('n_total', 'SNPP')] / r[('n_total', 'Aqua')],
                    'ratio_after': (r[('n_total', 'SNPP')] - r[('n_static', 'SNPP')]) / (r[('n_total', 'Aqua')] - r[('n_static', 'Aqua')]),
                    'aqua_n': r[('n_total', 'Aqua')]})
out['change_%'] = 100 * (out.ratio_after / out.ratio_before - 1)
out.reset_index().to_csv(f'{OUT}/ratio_snpp_aqua.csv', index=False, float_format='%.4f')
pd.set_option('display.width', 200)
print(imp[imp.region == 'GLOBAL'].round(3).to_string())
print(out.round(3).to_string())
# cells where static dominates
for s in ['Aqua', 'SNPP']:
    x = d[(d.satellite == s)]
    print(s, 'cells with static_share>=0.5:', {dn: int(((x.daynight == dn) & (x.static_share_n >= 0.5) & (x.n_total >= 10)).sum()) for dn in 'DN'},
          'of', {dn: int(((x.daynight == dn) & (x.n_total >= 10)).sum()) for dn in 'DN'})
