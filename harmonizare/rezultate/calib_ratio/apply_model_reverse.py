"""calib_ratio REVERSE conversion: Aqua MODIS (or Aqua-equivalent) monthly 0.25 deg values -> S-NPP VIIRS scale.
Same recipe family as the forward B5, roles swapped (target = S-NPP, input = Aqua), masked monthly table:
  k(cell, daynight, season) = K_region_season x rel(cell)
  K_region_season = sum(VIIRS)/sum(Aqua) per region x daynight x season, shrunk toward the region ratio: (V + n0s*K_reg)/(A + n0s)
  rel(cell)       = (cell ratio shrunk -> 2deg block -> region ratio, constant n0c) / region ratio; 1 if the cell/block was never seen
  pred = k * Aqua value.  Constants n0s, n0c per variable and day/night, chosen by leave-one-year-out within 2012-02..2017-12.
STRUCTURAL LIMIT (read before using): a multiplicative conversion of Aqua gives ZERO wherever Aqua saw nothing, but VIIRS
often detects fire there (at night ~86% of VIIRS-active cell-months, ~36% of VIIRS night detections have no Aqua detection).
The ratios are ratio-of-sums over ALL cell-months, so these missed detections are added back on average as an inflated factor
on the cells Aqua did see: regional/annual totals are about right, but the map is too concentrated (too few active cells,
too-high values where Aqua was active) and single cell-months, especially at night, are unreliable.
Intervals: 10-90% of obs/pred from leave-one-year-out residuals, by predicted-magnitude bin (cell-month level).
Usage: import apply_model_reverse as amr; out = amr.predict(df)  # df: ix, iy, year, month, daynight, n_sum, frp_sum (Aqua)"""
import os, sys, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, f'{ROOT}/scripts'); import eval_common as ec
BINS = {'n': [0, 3, 10, 30, 100, 300, 1000, 10000, np.inf], 'frp': [0, 10, 30, 100, 300, 1000, 10000, 100000, np.inf]}
def _keys(d):
    d = d.copy(); d['region'] = ec.region_of(d.ix.values, d.iy.values).astype(str); d['daynight'] = d.daynight.astype(str)
    d['season'] = ((d.month % 12) // 3).astype('int8'); d['b2'] = (d.ix // 8).astype('int32') * 1000 + d.iy // 8; return d
def fit_factors(cal, n0):
    """cal: paired cell-months ix,iy,month,daynight, t_n,t_frp (target VIIRS), i_n,i_frp (input Aqua).
    n0: {(var, dn): (n0_season, n0_cell)}"""
    d = _keys(cal); out = []
    for var in ('n', 'frp'):
        a, s = f't_{var}', f'i_{var}'
        for dn in ('D', 'N'):
            x = d[d.daynight == dn]; ns, nc = n0[(var, dn)]; kg = x[a].sum() / x[s].sum()
            r = x.groupby('region')[[a, s]].sum().reset_index(); r['kr'] = np.where(r[s] > 0, r[a] / r[s].clip(lower=1e-9), kg)
            rs = x.groupby(['region', 'season'])[[a, s]].sum().reset_index().merge(r[['region', 'kr']]); rs['k'] = (rs[a] + ns * rs.kr) / (rs[s] + ns)
            b = x.groupby(['region', 'b2'])[[a, s]].sum().reset_index().merge(r[['region', 'kr']]); b['kb'] = (b[a] + nc * b.kr) / (b[s] + nc)
            c = x.groupby(['region', 'b2', 'ix', 'iy'])[[a, s]].sum().reset_index().merge(b[['region', 'b2', 'kb', 'kr']]); c['k'] = (c[a] + nc * c.kb) / (c[s] + nc)
            # every region x season must exist: fill missing seasons with the region ratio
            full = r[['region', 'kr']].merge(pd.DataFrame({'season': np.arange(4, dtype='int8')}), how='cross').merge(rs[['region', 'season', 'k']], how='left')
            full['k'] = full.k.fillna(full.kr)
            out += [full.assign(level='region_season', var=var, daynight=dn)[['level', 'var', 'daynight', 'region', 'season', 'k']],
                    b.assign(level='b2', var=var, daynight=dn, k=b.kb / b.kr)[['level', 'var', 'daynight', 'region', 'b2', 'k']],
                    c.assign(level='cell', var=var, daynight=dn, k=c.k / c.kr)[['level', 'var', 'daynight', 'region', 'ix', 'iy', 'k']]]
    return pd.concat(out, ignore_index=True)
def load_factors():
    return pd.read_parquet(f'{HERE}/factors_reverse.parquet')
def predict(df, F=None, interval=True):
    F = load_factors() if F is None else F
    d = _keys(df); out = d[['ix', 'iy', 'year', 'month', 'daynight']].copy()
    for var, col in (('n', 'n_sum'), ('frp', 'frp_sum')):
        f = F[F['var'] == var]
        rs = f[f.level == 'region_season'][['daynight', 'region', 'season', 'k']].rename(columns={'k': 'krs'})
        b = f[f.level == 'b2'][['daynight', 'region', 'b2', 'k']].rename(columns={'k': 'kb'})
        c = f[f.level == 'cell'][['daynight', 'ix', 'iy', 'k']].rename(columns={'k': 'kc'})
        rs['season'] = rs.season.astype('int8'); b['b2'] = b.b2.astype('int32')
        c['ix'] = c.ix.astype(d.ix.dtype); c['iy'] = c.iy.astype(d.iy.dtype)
        m = d[['daynight', 'region', 'season', 'b2', 'ix', 'iy']].merge(rs, how='left').merge(b, how='left').merge(c, how='left')
        p = d[col].values * m.krs.values * m.kc.fillna(m.kb).fillna(1.0).values; out[f'pred_{var}'] = p
        if interval:
            iv = f[f.level == 'interval_cell']; nb = len(BINS[var]) - 1
            for dn in ('D', 'N'):
                q = iv[iv.daynight == dn].set_index('bin'); mm = (out.daynight == dn).values
                bi = np.clip(np.digitize(p[mm], BINS[var]) - 1, 0, nb - 1)
                lo = q.lo.reindex(range(nb)).ffill().bfill().values; hi = q.hi.reindex(range(nb)).ffill().bfill().values
                out.loc[mm, f'lo_{var}'] = p[mm] * lo[bi]; out.loc[mm, f'hi_{var}'] = p[mm] * hi[bi]
    return out
