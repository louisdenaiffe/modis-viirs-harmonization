"""04_build_final.py — assemble the harmonized 2000-2025 record (Aqua-MODIS-equivalent, 0.25 deg, monthly, day/night).
Run from project folder, repeat until it prints DONE:  python3 harmonizare/scripts/04_build_final.py [budget_s] [--force]
Source priority per month and day/night:
  before 2002-07 : Terra x regional Terra->Aqua factor (qc_stability)                         source = terra_backfill
  2002-07..2021-12: real Aqua; if Aqua month is flagged 'exclude' -> VIIRS-equivalent, else Terra back-fill
  2022-01 onwards : S-NPP VIIRS converted to Aqua-equivalent; if S-NPP month excluded -> real Aqua
VIIRS conversion: DAY = calib_ratio B5 v2 (region x season ratio x cell factor; BONA/BOAS day counts from n_best, split at 60N); NIGHT = calib_physics_ml P1 (weights per VIIRS FRP class).
Months flagged 'rescale' are divided by their coverage weight. Output: harmonizare/rezultate/final/"""
import duckdb, pandas as pd, numpy as np, sys, os, time, importlib.util
budget = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1][0] != '-' else 80
force = '--force' in sys.argv; t0 = time.time()
R = 'harmonizare'; OUT = f'{R}/rezultate/final'; os.makedirs(f'{OUT}/parts', exist_ok=True)
sys.path.insert(0, f'{R}/scripts'); import eval_common as ec
def mod(path, name):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
am_r = mod(f'{R}/rezultate/calib_ratio/apply_model_v2.py', 'am_r'); am_p = mod(f'{R}/rezultate/calib_physics_ml/apply_model.py', 'am_p')
FR = am_r.load_factors()
comp = pd.read_csv(f'{R}/rezultate/qc_stability/completeness_monthly.csv')
comp = comp[comp.daynight.isin(['D', 'N'])][['satellite', 'daynight', 'year', 'month', 'coverage', 'flag_month']]
con = duckdb.connect(); con.execute("SET memory_limit='700MB'; SET threads=2")
# Terra -> Aqua factors: region x calendar month x day/night, fitted on the 4 years closest to the back-fill period (2003-2006).
# (Back-cast test: nearest-window factors give median regional |bias| 3.0% vs 5.2% for a 10-year window.) Fallback + spread from qc_stability.
tf0 = pd.read_csv(f'{R}/rezultate/qc_stability/terra_to_aqua_factors.csv')[['region', 'month', 'daynight', 'f_n', 'f_frp', 'f_n_interannual_cv']]
_cells = pd.DataFrame({'ix': np.repeat(np.arange(1440), 720), 'iy': np.tile(np.arange(720), 1440)}); _cells['region'] = ec.region_of(_cells.ix.values, _cells.iy.values).astype(str); con.register('cells', _cells)
_w = con.execute(f"""SELECT region, daynight, year, month, satellite, sum(n_sum) n, sum(frp_sum) frp FROM read_parquet('{R}/data/grid/monthly_025/*.parquet')
    JOIN cells USING (ix, iy) WHERE satellite IN ('Aqua', 'Terra') AND year BETWEEN 2003 AND 2006 GROUP BY ALL""").df()
_bad = set(map(tuple, comp[(comp.flag_month != 'ok') & comp.satellite.isin(['Aqua', 'Terra'])][['year', 'month']].values))
_w = _w[~_w[['year', 'month']].apply(tuple, axis=1).isin(_bad)]
_w = _w.pivot_table(index=['region', 'daynight', 'month'], columns='satellite', values=['n', 'frp'], aggfunc='sum', fill_value=0); _w.columns = [f'{v}_{s}' for v, s in _w.columns]; _w = _w.reset_index()
tf = tf0.merge(_w, on=['region', 'month', 'daynight'], how='left')
_ok = tf.n_Terra.fillna(0) >= 50
tf['f_n'] = np.where(_ok, tf.n_Aqua / tf.n_Terra.clip(lower=1), tf.f_n); tf['f_frp'] = np.where(_ok & (tf.frp_Terra > 0), tf.frp_Aqua / tf.frp_Terra.clip(lower=1), tf.f_frp)
tf = tf[['region', 'month', 'daynight', 'f_n', 'f_frp', 'f_n_interannual_cv']]; tf.to_csv(f'{OUT}/terra_to_aqua_factors_used.csv', index=False)
KEY = ['ix', 'iy', 'year', 'month', 'daynight']; COLS = KEY + ['n_eq', 'frp_eq', 'lo_n', 'hi_n', 'lo_frp', 'hi_frp', 'source', 'flag']

def qc(df, sat):
    """attach completeness flag, drop excluded months, rescale partial months"""
    c = comp[comp.satellite == sat].drop(columns='satellite')
    df = df.merge(c, on=['daynight', 'year', 'month'], how='left'); df['flag_month'] = df.flag_month.fillna('ok'); df['coverage'] = df.coverage.fillna(1.0)
    df = df[df.flag_month != 'exclude'].copy(); s = np.where(df.flag_month == 'rescale', 1 / df.coverage.clip(lower=0.5), 1.0)
    for c_ in ['n_eq', 'frp_eq', 'lo_n', 'hi_n', 'lo_frp', 'hi_frp']: df[c_] = df[c_] * s
    df['flag'] = df.flag_month; return df

def year_part(y):
    frames = {}
    g = f"{R}/data/grid/monthly_025/monthly_{y}.parquet"
    if not os.path.exists(g): return None
    a = con.execute(f"SELECT {', '.join(KEY)}, n_sum, frp_sum FROM '{g}' WHERE satellite='Aqua' AND year={y}").df()
    if len(a):
        a['n_eq'] = a.n_sum.astype(float); a['frp_eq'] = a.frp_sum.astype(float)
        a['lo_n'] = a.n_eq; a['hi_n'] = a.n_eq; a['lo_frp'] = a.frp_eq; a['hi_frp'] = a.frp_eq; a['source'] = 'aqua'; frames['aqua'] = qc(a, 'Aqua')
    v = con.execute(f"SELECT * FROM '{g}' WHERE satellite='SNPP' AND year={y}").df()
    if len(v):
        p = am_r.predict(v, FR)                                   # B5 for all rows (gives interval multipliers too)
        pn, pf = am_p.predict(v, counts='p1')                     # P1 (FRP-class weights)
        night = (v.daynight == 'N').values
        for var, alt in (('n', pn), ('frp', pf)):
            base = p[f'pred_{var}'].values.copy()
            lo = np.divide(p[f'lo_{var}'].values, base, out=np.full(len(base), np.nan), where=base > 0)
            hi = np.divide(p[f'hi_{var}'].values, base, out=np.full(len(base), np.nan), where=base > 0)
            val = np.where(night, alt, base)
            v[f'{var}_eq'] = val; v[f'lo_{var}'] = val * np.nan_to_num(lo, nan=0.0); v[f'hi_{var}'] = val * np.nan_to_num(hi, nan=3.0)
        v['source'] = 'viirs_harmonized'
        rg = v.assign(region=ec.region_of(v.ix.values, v.iy.values).astype(str)).groupby(['region', 'daynight', 'year', 'month'])[['n_eq', 'frp_eq', 'n_sum', 'frp_sum']].sum().reset_index()
        rg.to_csv(f'{OUT}/parts/viirs_eq_region_{y}.csv', index=False)
        frames['viirs'] = qc(v[KEY + ['n_eq', 'frp_eq', 'lo_n', 'hi_n', 'lo_frp', 'hi_frp', 'source']], 'SNPP')
    if y <= 2021:
        t = con.execute(f"SELECT {', '.join(KEY)}, n_sum, frp_sum FROM '{g}' WHERE satellite='Terra' AND year={y}").df()
        if len(t):
            t['region'] = ec.region_of(t.ix.values, t.iy.values).astype(str); t = t.merge(tf, on=['region', 'month', 'daynight'], how='left')
            for c_ in ('f_n', 'f_frp'): t[c_] = t[c_].fillna(1.0)
            cv = t.f_n_interannual_cv.fillna(0.3).clip(0.05, 0.6)
            t['n_eq'] = t.n_sum * t.f_n; t['frp_eq'] = t.frp_sum * t.f_frp
            t['lo_n'] = t.n_eq * (1 - 1.28 * cv).clip(lower=0); t['hi_n'] = t.n_eq * (1 + 1.28 * cv)
            t['lo_frp'] = t.frp_eq * (1 - 1.28 * cv).clip(lower=0); t['hi_frp'] = t.frp_eq * (1 + 1.28 * cv)
            t['source'] = 'terra_backfill'; frames['terra'] = qc(t, 'Terra')
    out = []
    for m in range(1, 13):
        ym = y * 100 + m
        order = ['terra'] if ym < 200207 else (['aqua', 'viirs', 'terra'] if ym <= 202112 else ['viirs', 'aqua'])
        for dn in 'DN':
            for s in order:
                if s in frames:
                    f = frames[s]; f = f[(f.month == m) & (f.daynight == dn)]
                    if len(f): out.append(f[COLS]); break
    return pd.concat(out, ignore_index=True) if out else None

done = True
for y in range(2000, 2026):
    dst = f'{OUT}/parts/final_{y}.parquet'
    if os.path.exists(dst) and not force: continue
    if time.time() - t0 > budget: done = False; print('budget reached; rerun'); break
    d = year_part(y)
    if d is None: continue
    for c_ in ['n_eq', 'frp_eq', 'lo_n', 'hi_n', 'lo_frp', 'hi_frp']: d[c_] = d[c_].astype('float32')
    d.to_parquet(dst, index=False, compression='zstd')
    print(y, len(d), d.groupby('source').n_eq.sum().round(0).to_dict(), round(time.time() - t0), 's', flush=True)
print('DONE' if done else 'PARTIAL')
