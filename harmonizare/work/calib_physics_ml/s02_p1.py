# P1: FRP-floor pseudo-MODIS: Aqua = sum_b w_b * VIIRS_b, w>=0. LS and Poisson fits, global and region x dn. Year-blocked CV.
import numpy as np, pandas as pd, sys, json
from scipy.optimize import nnls, minimize
sys.path.insert(0, 'work/calib_physics_ml'); from lib import *
def fit_ls(X, y): return nnls(X.astype(float), y.astype(float), maxiter=2000)[0] if len(y) else np.zeros(X.shape[1])
def fit_ls_gram(X, y):  # NNLS via Gram (fast for millions of rows)
    X = X.astype(float); G = X.T @ X + 1e-6 * np.eye(X.shape[1]); b = X.T @ y
    L = np.linalg.cholesky(G); return nnls(L.T, np.linalg.solve(L, b))[0]
def fit_pois(X, y):
    X = X.astype(float); y = y.astype(float); w0 = np.full(X.shape[1], max(y.sum(), 1) / max(X.sum(), 1))
    def f(w):
        mu = X @ w + 1e-9; return (mu - y * np.log(mu)).sum(), X.T @ (1 - y / mu)
    return minimize(f, w0, jac=True, method='L-BFGS-B', bounds=[(0, None)] * X.shape[1]).x
FITS = {'ls': fit_ls_gram, 'pois': fit_pois}
def fit(d, xc, yc, how, scope, shrink=0):
    W = {}
    wg = FITS[how](d[xc].values, d[yc].values); W['ALL'] = wg
    if scope == 'region':
        for r, g in d.groupby('region', observed=True):
            if len(g) < 50: W[r] = wg; continue
            wr = FITS[how](g[xc].values, g[yc].values)
            W[r] = wr if not shrink else (1 - shrink) * wr + shrink * wg
    return W
def pred(d, W, xc):
    p = np.zeros(len(d))
    for r in d.region.cat.categories:
        m = (d.region == r).values
        if m.any(): p[m] = d.loc[m, xc].values.astype(float) @ W.get(r, W['ALL'])
    return p
if __name__ == '__main__':
    import os, time; t0 = time.time()
    dn, var, how = sys.argv[1:4]; xc, yc = (CB, 'a_n') if var == 'n' else (FB, 'a_frp')
    d = cal(dn, xc + [yc]); print('loaded', len(d), round(time.time() - t0, 1), flush=True)
    res = {k: [] for k in ('global0', 'region0', 'region0.5', 'region0.25')}
    for yv in range(2012, 2018):
        tr, va = d[d.year != yv], d[d.year == yv]
        W = fit(tr, xc, yc, how, 'region')
        Wg = {'ALL': W['ALL']}
        res['global0'].append(quick(va, pred(va, Wg, xc), yc))
        res['region0'].append(quick(va, pred(va, W, xc), yc))
        for sh in (0.5, 0.25):
            Ws = {r: (1 - sh) * w + sh * W['ALL'] for r, w in W.items()}
            res[f'region{sh}'].append(quick(va, pred(va, Ws, xc), yc))
    out = []
    for k, v in res.items():
        r = pd.DataFrame(v).mean().to_dict(); r.update(dn=dn, var=var, how=how, scope=k); out.append(r)
    o = pd.DataFrame(out).round(4); print(o.to_string(), round(time.time() - t0, 1))
    f = f'{W_}/p1_cv.csv' if False else 'work/calib_physics_ml/p1_cv.csv'
    o.to_csv(f, mode='a', header=not os.path.exists(f), index=False)
