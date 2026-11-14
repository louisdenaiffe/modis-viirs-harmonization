# production recipe (DAY=B5 calib_ratio, NIGHT=P1 region weights) on test years + Aqua truth, per cell-month; plus calibration-activity groups
import duckdb, pandas as pd, numpy as np, sys, os, importlib.util
R = '.'; sys.path.insert(0, 'scripts'); import eval_common as ec
def mod(p, n):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
W = 'work/calib_physics_ml'; KEY = ['ix', 'iy', 'year', 'month', 'daynight']
con = duckdb.connect(); con.execute("SET memory_limit='600MB'; SET threads=2; SET temp_directory='data/_ducktmp/calib_physics_ml'")
step = sys.argv[1]
if step == 'groups':
    g = con.execute(f"""SELECT ix, iy, daynight, sum(n_sum) cal_s_n FROM read_parquet('data/grid/monthly_025/monthly_201[2-7].parquet')
        WHERE satellite='SNPP' AND {ec.ym_filter(ec.CAL)} GROUP BY ALL""").df()
    g['b2'] = (g.ix // 8) * 1000 + g.iy // 8
    g['b2_s_n'] = g.groupby(['daynight', 'b2']).cal_s_n.transform('sum')
    g.to_parquet(f'{W}/groups.parquet', index=False); print(len(g))
    fl = str(['data/grid/monthly_025/monthly_%d.parquet' % y for y in range(2018, 2026)])
    v = con.execute(f"SELECT ix, iy, daynight, sum(n_sum) v_n FROM read_parquet({fl}) WHERE satellite='SNPP' GROUP BY ALL").df()
    v.to_parquet(f'{W}/viirs_1825.parquet', index=False); print(len(v))
else:
    y = int(step)
    am_r = mod('rezultate/calib_ratio/apply_model.py', 'am_r'); am_p = mod('rezultate/calib_physics_ml/apply_model.py', 'am_p')
    g = f'data/grid/monthly_025/monthly_{y}.parquet'
    v = con.execute(f"SELECT * FROM '{g}' WHERE satellite='SNPP'").df()
    p = am_r.predict(v, interval=False); pn, pf = am_p.predict(v, counts='p1'); night = (v.daynight == 'N').values
    v['pred_n'] = np.where(night, pn, p.pred_n.values); v['pred_frp'] = np.where(night, pf, p.pred_frp.values)
    a = con.execute(f"SELECT {', '.join(KEY)}, n_sum obs_n, frp_sum obs_frp FROM '{g}' WHERE satellite='Aqua'").df()
    d = v[KEY + ['pred_n', 'pred_frp']].merge(a, on=KEY, how='outer').fillna(0)
    d = d[(d.year * 12 + d.month).between(*ec.TEST)]
    for yy, mm in ec.EXCLUDE: d = d[~((d.year == yy) & (d.month == mm))]
    for c in ('pred_n', 'pred_frp', 'obs_n', 'obs_frp'): d[c] = d[c].astype('float32')
    d.to_parquet(f'{W}/prod_{y}.parquet', index=False, compression='zstd'); print(y, len(d), d[['pred_n', 'obs_n']].sum().round().to_dict())
