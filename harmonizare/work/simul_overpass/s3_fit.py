"""Step 3 analysis: binned detection probability + logistic fit in log10(FRP); figure + CSVs."""
import sys, os, glob; sys.path.insert(0, os.path.dirname(__file__)); from common import *
import numpy as np, pandas as pd
from scipy.optimize import minimize
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
h = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{W}/s3/hist_*.parquet'))])
print('clusters total', h.ncl.sum(), 'frp<=0 clusters', h[h.lbin == -9].ncl.sum())
h = h[h.lbin > -9]
def fit(g, k='det_q', plateau=False):
    x = g.lbin.values + 0.05; n = g.ncl.values.astype(float); d = g[k].values.astype(float)
    def nll(p):
        top = 1 / (1 + np.exp(-p[2])) if plateau else 1.0
        pr = np.clip(top / (1 + np.exp(-(x - p[0]) * p[1])), 1e-9, 1 - 1e-9)
        return -(d * np.log(pr) + (n - d) * np.log(1 - pr)).sum()
    p = minimize(nll, [1.0, 3.0, 2.0], method='Nelder-Mead', options=dict(maxiter=4000, xatol=1e-5, fatol=1e-3)).x
    return (p[0], p[1], 1 / (1 + np.exp(-p[2]))) if plateau else (p[0], p[1])
rows, curves = [], []
groups = [('all', None)] + [(s, s) for s in ['1.0-1.5', '1.5-2.0', '2.0-3.0', '3.0-4.8']]
for dn in 'DN':
    for gname, s in groups:
        g = h[h.dn == dn] if s is None else h[(h.dn == dn) & (h.scb == s)]
        b = g.groupby('lbin')[['ncl', 'npix', 'frp', 'det_q', 'det_any', 'det_tol', 'npix_det_q', 'frp_det_q', 'npix_det_tol', 'frp_det_tol']].sum().reset_index()
        b = b[(b.lbin >= -0.5) & (b.lbin < 3.5)]
        x50, k = fit(b); x90 = x50 + np.log(9) / k
        xa50, ka = fit(b, 'det_any'); xt50, kt = fit(b, 'det_tol'); xp50, kp, top = fit(b, 'det_q', True)
        hi = b[b.lbin >= 2.0]
        tot = g[['ncl', 'npix', 'frp', 'det_q', 'det_tol', 'npix_det_q', 'frp_det_q', 'npix_det_tol', 'frp_det_tol']].sum()
        rows.append(dict(daynight=dn, scan_proxy=gname, clusters=int(tot.ncl), frp50_MW=10**x50, frp90_MW=10**x90, slope_per_log10=k,
                         frp50_anyconf_MW=10**xa50, P_obs_at_ge100MW=hi.det_q.sum() / hi.ncl.sum(), P_obs_tol_at_ge100MW=hi.det_tol.sum() / hi.ncl.sum(),
                         tol_frp50_MW=10**xt50, tol_frp90_MW=10**(xt50 + np.log(9) / kt), tol_slope=kt, plat_top=top, plat_frp_half_MW=10**xp50, plat_slope=kp,
                         tol_share_clusters_det=tot.det_tol / tot.ncl, tol_share_pix_det=tot.npix_det_tol / tot.npix, tol_share_frp_det=tot.frp_det_tol / tot.frp,
                         share_clusters_detected=tot.det_q / tot.ncl, share_viirs_pixels_in_detected=tot.npix_det_q / tot.npix,
                         share_viirs_frp_in_detected=tot.frp_det_q / tot.frp))
        b['daynight'] = dn; b['scan_proxy'] = gname; b['P_det_q'] = b.det_q / b.ncl; b['P_det_any'] = b.det_any / b.ncl; b['P_det_tol'] = b.det_tol / b.ncl; b['P_fit_tol'] = 1 / (1 + np.exp(-(b.lbin + 0.05 - xt50) * kt))
        b['frp_bin_lo_MW'] = 10**b.lbin; b['P_fit'] = 1 / (1 + np.exp(-(b.lbin + 0.05 - x50) * k)); curves.append(b)
res = pd.DataFrame(rows); cur = pd.concat(curves)
res.to_csv(f'{R}/detection_curve_fit.csv', index=False)
cur[['daynight', 'scan_proxy', 'frp_bin_lo_MW', 'ncl', 'det_q', 'P_det_q', 'P_det_any', 'P_fit', 'P_det_tol', 'P_fit_tol', 'npix', 'frp']].to_csv(f'{R}/detection_curve_bins.csv', index=False)
pd.set_option('display.width', 250); print(res.round(3).to_string())
sel = cur[cur.scan_proxy == 'all']
for dn in 'DN':
    s = sel[sel.daynight == dn]
    print(dn, 'bins (FRP_lo MW: P_obs/P_fit/n):', '; '.join(f'{a:.2g}:{p:.2f}/{f:.2f}/{n}' for a, p, f, n in zip(s.frp_bin_lo_MW, s.P_det_q, s.P_fit, s.ncl) if n >= 30))
    print(dn, 'TOLERANT bins (FRP_lo: P_obs/P_fit):', '; '.join(f'{a:.2g}:{p:.2f}/{f:.2f}' for a, p, f, n in zip(s.frp_bin_lo_MW, s.P_det_tol, s.P_fit_tol, s.ncl) if n >= 30))
fig, ax = plt.subplots(1, 2, figsize=(12.5, 5), sharey=True)
cols = {'1.0-1.5': '#2a6fdb', '1.5-2.0': '#2fa37a', '2.0-3.0': '#e0a030', '3.0-4.8': '#d0443e', 'all': 'k'}
xx = np.linspace(-0.5, 3.5, 200)
for i, dn in enumerate('DN'):
    a = ax[i]
    for gname in ['1.0-1.5', '1.5-2.0', '2.0-3.0', '3.0-4.8', 'all']:
        s = cur[(cur.daynight == dn) & (cur.scan_proxy == gname) & (cur.ncl >= 30)]
        r = res[(res.daynight == dn) & (res.scan_proxy == gname)].iloc[0]
        a.plot(s.frp_bin_lo_MW * 10**0.05, s.P_det_tol, 'o', ms=3.5, color=cols[gname], alpha=0.8)
        a.plot(10**xx, 1 / (1 + np.exp(-(xx - np.log10(r.tol_frp50_MW)) * r.tol_slope)), '-', color=cols[gname], lw=2.5 if gname == 'all' else 1.3,
               label=('all scans' if gname == 'all' else f'MODIS scan {gname} km') + f': 50% at {r.tol_frp50_MW:.0f} MW, 90% at {r.tol_frp90_MW:.0f} MW')
    s = cur[(cur.daynight == dn) & (cur.scan_proxy == 'all') & (cur.ncl >= 30)]
    a.plot(s.frp_bin_lo_MW * 10**0.05, s.P_det_q, 'k--', lw=1, label='all scans, strict 1x footprint match (observed)')
    a.set_xscale('log'); a.set_xlim(0.3, 2000); a.set_xlabel('Fire power seen by S-NPP VIIRS in a ~1 km cell (MW)')
    a.set_title({'D': 'Day (13:30)', 'N': 'Night (01:30)'}[dn] + ': chance that Aqua MODIS also detects it'); a.grid(alpha=0.3, which='both')
    a.axhline(0.5, color='grey', lw=0.6); a.legend(fontsize=7.3, loc='upper left')
ax[0].set_ylabel('Probability Aqua MODIS detects (type 0, conf >= nominal)')
fig.suptitle('MODIS detection curve learned from 4.26 M S-NPP fire clusters seen by both satellites within 10 min (2015, 2019, 2021)', fontsize=10)
fig.tight_layout(); fig.savefig(f'{R}/fig_detection_curve.png', dpi=140); print('fig ok')
