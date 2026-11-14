import pandas as pd, numpy as np, duckdb, sys; sys.path.insert(0, 'scripts'); import eval_common as ec
W = 'work/calib_physics_ml'; pd.set_option('display.width', 250)
g = pd.read_parquet(f'{W}/groups.parquet'); v = pd.read_parquet(f'{W}/viirs_1825.parquet')
def grp(df):
    m = df.merge(g[['ix', 'iy', 'daynight', 'cal_s_n']], how='left', on=['ix', 'iy', 'daynight'])
    m['b2'] = (m.ix // 8) * 1000 + m.iy // 8
    bt = g.groupby(['daynight', 'b2']).cal_s_n.sum().rename('b2_s_n').reset_index(); m = m.merge(bt, how='left', on=['daynight', 'b2'])
    s, b = m.cal_s_n.fillna(0).values, m.b2_s_n.fillna(0).values
    m['grp'] = np.where(s >= 1000, '1_cell', np.where(b >= 1000, '2_block2deg', '3_region_only')); return m
vv = grp(v); cov = vv.groupby(['daynight', 'grp']).v_n.sum(); 0 and print('share of 2018-2025 VIIRS detections by factor group\n', (cov / cov.groupby(level=0).transform('sum')).round(4))
d = grp(pd.concat([pd.read_parquet(f'{W}/prod_{y}.parquet') for y in range(2018, 2022)], ignore_index=True))
rows = []
for (dn, gr), x in d.groupby(['daynight', 'grp']):
    r = dict(daynight=dn, grp=gr, obs_n=x.obs_n.sum(), bias_n=x.pred_n.sum() / x.obs_n.sum() - 1, bias_frp=x.pred_frp.sum() / x.obs_frp.sum() - 1)
    for lo, hi in ((10, 100), (100, 1e9)):
        y = x[(x.obs_n >= lo) & (x.obs_n < hi)]; r[f'cell_mederr_n_{lo}+'] = np.median(np.abs(y.pred_n / y.obs_n - 1)) if len(y) else np.nan; r[f'ncells_{lo}+'] = len(y)
    x = x.assign(region=ec.region_of(x.ix.values, x.iy.values)); rr = x.groupby(['region', 'year']).agg(o=('obs_n', 'sum'), p=('pred_n', 'sum')); rr = rr[rr.o >= 100]
    r['regyear_med_abs_bias_n'] = np.median(np.abs(rr.p / rr.o - 1)) if len(rr) else np.nan; rows.append(r)
G = pd.DataFrame(rows).round(3); pass; G.to_csv('rezultate/calib_physics_ml/accuracy_by_factor_group.csv', index=False)
# worst 1-degree blocks
d['bx'], d['by'] = d.ix // 4, d.iy // 4
b = d.groupby(['daynight', 'bx', 'by'])[['pred_n', 'obs_n', 'pred_frp', 'obs_frp']].sum().reset_index()
c = duckdb.connect(); c.execute("SET memory_limit='500MB'; SET threads=2")
fl = str(['data/grid/monthly_025/monthly_%d.parquet' % y for y in range(2018, 2022)])
f = c.execute(f"""SELECT daynight, ix//4 bx, iy//4 "by", count(DISTINCT year*12+month) months_active, sum(n_sum) v_n, sum(n_static) v_static, sum(n_all) v_all,
   sum(frp_sum)/nullif(sum(n_sum),0) frp_per_px, sum(c_lt3)/nullif(sum(n_sum),0) sh_lt3, sum(ops)/nullif(sum(days),0) ops_per_day
   FROM read_parquet({fl}) WHERE satellite='SNPP' AND year*12+month BETWEEN {ec.TEST[0]} AND {ec.TEST[1]} GROUP BY ALL""").df()
b = b.merge(f, how='left', on=['daynight', 'bx', 'by'])
b['lon'] = (b.bx * 1 - 180 + 0.5); b['lat'] = (b.by * 1 - 90 + 0.5); b['region'] = ec.region_of(b.bx.values * 4 + 1, b.by.values * 4 + 1)
b['ratio_n'] = b.pred_n / b.obs_n; b['ratio_frp'] = b.pred_frp / b.obs_frp; b['static_share'] = b.v_static / b.v_all
out = []
for dn, thr in (('D', 1000), ('N', 300)):
    x = b[(b.daynight == dn) & (b.obs_n >= thr)].copy(); x['abslog'] = np.abs(np.log(x.ratio_n)); out.append(x.nlargest(15 if dn == 'D' else 8, 'abslog'))
o = pd.concat(out)[['daynight', 'lat', 'lon', 'region', 'obs_n', 'pred_n', 'ratio_n', 'ratio_frp', 'months_active', 'static_share', 'frp_per_px', 'sh_lt3', 'ops_per_day']].round(3)
print(o.to_string(index=False)); o.to_csv('rezultate/calib_physics_ml/worst_1deg_blocks.csv', index=False)
x = b[(b.daynight == 'D') & (b.obs_n >= 1000)]; print('D blocks>=1000:', len(x), 'share within +-20%:', round((np.abs(x.ratio_n - 1) <= .2).mean(), 3), 'within 50%', round((np.abs(x.ratio_n - 1) <= .5).mean(), 3))
