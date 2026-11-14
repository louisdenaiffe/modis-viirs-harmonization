"""calib_ratio production recipe: S-NPP VIIRS monthly (0.25 deg, type 0, conf not low) -> Aqua-MODIS-equivalent.
k(cell, daynight, season) = K_region_season  x  rel_spatial(cell)
  K_region_season = ratio of sums Aqua/SNPP per region x daynight x season, shrunk to the region ratio (n0: counts 3000, FRP 1000 MW)
  rel_spatial     = (cell ratio shrunk -> 2deg block -> region; n0 counts 1000, FRP 10000 MW) / region ratio   (1 if cell/block unseen)
Calibration 2012-02..2017-12. Interval: multiplicative 10-90% factors by predicted-magnitude bin (leave-one-year-out residuals).
Usage: import apply_model as am; out = am.predict(df)   # df: ix, iy, year, month, daynight, n_sum, frp_sum (SNPP)"""
import os, sys, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, f'{ROOT}/scripts'); import eval_common as ec
N0 = {'n': (3000., 1000.), 'frp': (1000., 10000.)}
BINS = {'n': [0, 1, 3, 10, 30, 100, 1000, np.inf], 'frp': [0, 10, 30, 100, 300, 1000, 10000, np.inf]}
def _keys(d):
    d = d.copy(); d['region'] = ec.region_of(d.ix.values, d.iy.values).astype(str); d['daynight'] = d.daynight.astype(str)
    d['season'] = ((d.month % 12) // 3).astype('int8'); d['b2'] = (d.ix // 8).astype('int32') * 1000 + d.iy // 8; return d
def fit_factors(cal):
    """cal: paired cell-months with ix,iy,month,daynight,a_n,a_frp,s_n,s_frp -> long factor table"""
    d = _keys(cal); out = []
    for var, (a, s) in {'n': ('a_n', 's_n'), 'frp': ('a_frp', 's_frp')}.items():
        n_s, n_c = N0[var]
        g = d.groupby('daynight')[[a, s]].sum(); kg = g[a] / g[s]
        r = d.groupby(['daynight', 'region'])[[a, s]].sum().reset_index(); r['kr'] = np.where(r[s] > 0, r[a] / r[s].clip(lower=1e-9), r.daynight.map(kg))
        rs = d.groupby(['daynight', 'region', 'season'])[[a, s]].sum().reset_index().merge(r[['daynight', 'region', 'kr']])
        rs['k'] = (rs[a] + n_s * rs.kr) / (rs[s] + n_s)
        b = d.groupby(['daynight', 'region', 'b2'])[[a, s]].sum().reset_index().merge(r[['daynight', 'region', 'kr']])
        b['kb'] = (b[a] + n_c * b.kr) / (b[s] + n_c)
        c = d.groupby(['daynight', 'region', 'b2', 'ix', 'iy'])[[a, s]].sum().reset_index().merge(b[['daynight', 'region', 'b2', 'kb', 'kr']])
        c['k'] = (c[a] + n_c * c.kb) / (c[s] + n_c)
        out += [rs.assign(level='region_season', var=var, k=rs.k)[['level', 'var', 'daynight', 'region', 'season', 'k']],
                b.assign(level='b2', var=var, k=b.kb / b.kr)[['level', 'var', 'daynight', 'region', 'b2', 'k']],
                c.assign(level='cell', var=var, k=c.k / c.kr)[['level', 'var', 'daynight', 'region', 'ix', 'iy', 'k']]]
    return pd.concat(out, ignore_index=True)
def load_factors():
    return pd.read_parquet(f'{HERE}/factors.parquet')
def predict(df, F=None, interval=True):
    F = load_factors() if F is None else F
    d = _keys(df); out = d[['ix', 'iy', 'year', 'month', 'daynight']].copy()
    for var, col in (('n', 'n_sum'), ('frp', 'frp_sum')):
        f = F[F['var'] == var]
        rs = f[f.level == 'region_season'][['daynight', 'region', 'season', 'k']].rename(columns={'k': 'krs'})
        b = f[f.level == 'b2'][['daynight', 'region', 'b2', 'k']].rename(columns={'k': 'kb'})
        c = f[f.level == 'cell'][['daynight', 'ix', 'iy', 'k']].rename(columns={'k': 'kc'})
        for t in (rs, b, c):
            for kk in ('season', 'ix', 'iy'):
                if kk in t: t[kk] = t[kk].astype(d[kk].dtype)
        m = d[['daynight', 'region', 'season', 'b2', 'ix', 'iy']].merge(rs, how='left').merge(b, how='left').merge(c, how='left')
        k = m.krs.values * m.kc.fillna(m.kb).fillna(1.0).values
        p = d[col].values * k; out[f'pred_{var}'] = p
        if interval:
            iv = f[f.level == 'interval_cell']
            for dn in ('D', 'N'):
                q = iv[iv.daynight == dn].sort_values('bin'); mm = (out.daynight == dn).values
                bi = np.clip(np.digitize(p[mm], BINS[var]) - 1, 0, len(BINS[var]) - 2)
                lo = q.set_index('bin').lo.reindex(range(len(BINS[var]) - 1)).ffill().bfill().values
                hi = q.set_index('bin').hi.reindex(range(len(BINS[var]) - 1)).ffill().bfill().values
                out.loc[mm, f'lo_{var}'] = p[mm] * lo[bi]; out.loc[mm, f'hi_{var}'] = p[mm] * hi[bi]
    return out

RB = {'n': [0, 100, 1000, 10000, np.inf], 'frp': [0, 1e3, 1e4, 1e5, np.inf]}
def regional_interval(pred_total, var, daynight, F=None):
    """10-90% bounds for a summed (region-month) Aqua-equivalent prediction."""
    F = load_factors() if F is None else F
    q = F[(F.level == 'interval_regionmonth') & (F['var'] == var) & (F.daynight == daynight)].set_index('bin')
    p = np.asarray(pred_total, float); b = np.clip(np.digitize(p, RB[var]) - 1, 0, len(RB[var]) - 2)
    lo = q.lo.reindex(range(len(RB[var]) - 1)).ffill().bfill().values[b]; hi = q.hi.reindex(range(len(RB[var]) - 1)).ffill().bfill().values[b]
    return p * lo, p * hi

if __name__ == '__main__':  # python3 rezultate/calib_ratio/apply_model.py 2012 2025 -> rezultate/calib_ratio/harmonized_regionmonth.csv
    import duckdb
    y0, y1 = (int(a) for a in sys.argv[1:3]) if len(sys.argv) > 2 else (2012, 2025); F = load_factors(); out = []
    for y in range(y0, y1 + 1):
        v = duckdb.connect().execute(f"SELECT ix,iy,year,month,daynight,n_sum,frp_sum FROM read_parquet('{ROOT}/data/grid/monthly_025/monthly_{y}.parquet') WHERE satellite='SNPP'").df()
        p = predict(v, F); p['region'] = ec.region_of(p.ix.values, p.iy.values)
        out.append(p.groupby(['region', 'daynight', 'year', 'month'])[['pred_n', 'pred_frp']].sum().reset_index()); print(y, flush=True)
    R = pd.concat(out)
    for var in ('n', 'frp'):
        for dn in ('D', 'N'):
            m = R.daynight == dn; R.loc[m, f'lo_{var}'], R.loc[m, f'hi_{var}'] = regional_interval(R.loc[m, f'pred_{var}'], var, dn, F)
    R.to_csv(f'{HERE}/harmonized_regionmonth.csv', index=False)
