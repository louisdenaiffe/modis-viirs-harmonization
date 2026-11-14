import sys, os, duckdb, numpy as np, pandas as pd
sys.path.insert(0, 'scripts'); import eval_common as ec
W = 'work/calib_ratio'
VARS = {'n': ('a_n', 's_n'), 'frp': ('a_frp', 's_frp')}
def con():
    c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='data/_ducktmp/calib_ratio'"); return c
def load(y0, m0, y1, m1, extra=''):
    d = con().execute(f"""SELECT ix,iy,year,month,daynight,region,a_n,a_frp,s_n,s_frp{extra} FROM read_parquet('{W}/pair_*.parquet')
        WHERE (year*12+month) BETWEEN {y0*12+m0} AND {y1*12+m1}""").df()
    for k in ('daynight', 'region'): d[k] = d[k].astype('category')
    d['a_n'] = d.a_n.astype('float32'); d['s_n'] = d.s_n.astype('float32')
    return add_keys(d)
def add_keys(d):
    d['b1'] = ((d.ix // 4).astype('int32') * 1000 + d.iy // 4).astype('int32')
    d['b2'] = ((d.ix // 8).astype('int32') * 1000 + d.iy // 8).astype('int32')
    d['cell'] = (d.ix.astype('int32') * 1000 + d.iy).astype('int32')
    lat = (d.iy + 0.5) * 0.25 - 90; lon = (d.ix + 0.5) * 0.25 - 180
    d['latb'] = (np.floor(lat / 10)).astype('int8')
    d['sect'] = np.where(lon < -30, 0, np.where(lon < 60, 1, 2)).astype('int8')
    d['season'] = ((d.month % 12) // 3).astype('int8')  # 0 DJF 1 MAM 2 JJA 3 SON
    return d
CAL = (2012, 2, 2017, 12); TEST = (2018, 1, 2021, 12)
CAL_YEARS = range(2012, 2018)

def level_stats(fit, keys, var):
    a, s = VARS[var]
    g = fit.groupby(['daynight'] + keys, observed=True)[[a, s]].sum().reset_index()
    return g.rename(columns={a: 'A', s: 'S'})

def hier_factors(fit, tgt, chain, var, n0):
    """k for each row of tgt. chain = list of key-lists from coarse to fine (after global). n0 scalar or list per level."""
    a, s = VARS[var]
    g = fit.groupby('daynight', observed=True)[[a, s]].sum(); kg = (g[a] / g[s])
    k = tgt.daynight.map(kg).astype(float).values
    n0s = n0 if isinstance(n0, (list, tuple)) else [n0] * len(chain)
    for keys, nn in zip(chain, n0s):
        st = level_stats(fit, keys, var)
        m = tgt[['daynight'] + keys].merge(st, on=['daynight'] + keys, how='left')
        A = m.A.fillna(0).values; S = m.S.fillna(0).values
        k = (A + nn * k) / (S + nn) if nn > 0 else np.where(S > 0, A / np.maximum(S, 1e-9), k)
    return k

def hier_stats(fit, tgt, chain, var):
    """precompute (A,S) arrays for each level for fast n0 search"""
    a, s = VARS[var]
    g = fit.groupby('daynight', observed=True)[[a, s]].sum(); kg = (g[a] / g[s])
    k0 = tgt.daynight.map(kg).astype(float).values; L = []
    for keys in chain:
        st = level_stats(fit, keys, var)
        m = tgt[['daynight'] + keys].merge(st, on=['daynight'] + keys, how='left')
        L.append((m.A.fillna(0).values, m.S.fillna(0).values))
    return k0, L
def hier_apply(k0, L, n0s):
    k = k0
    for (A, S), nn in zip(L, n0s): k = (A + nn * k) / (S + nn)
    return k

def to_pred(tgt, kn, kf):
    p = tgt[ec.KEYS].copy(); p['pred_n'] = tgt.s_n.values * kn; p['pred_frp'] = tgt.s_frp.values * kf
    p['daynight'] = p.daynight.astype(str); return p
