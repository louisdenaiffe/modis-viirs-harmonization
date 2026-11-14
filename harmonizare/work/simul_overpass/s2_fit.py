"""Step 2 analysis: VIIRS pixels per MODIS pixel and summed-VIIRS-FRP / MODIS-FRP vs MODIS scan; polynomial fits; figure."""
import sys, os, glob; sys.path.insert(0, os.path.dirname(__file__)); from common import *
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{W}/s2/px_*.parquet'))])
edges = np.array([1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 4.81])
d['sb'] = pd.cut(d.scan, edges, right=False, labels=False)
print('Aqua pixels', len(d), dict(d.dn.value_counts()))
rows = []
for dn in 'DN':
    for b in range(len(edges) - 1):
        g = d[(d.dn == dn) & (d.sb == b)]
        if len(g) < 50: continue
        w = g[g.nv > 0]; lr = np.log10(w.vfrp.clip(lower=0.01) / w.mfrp.clip(lower=0.01))
        rows.append(dict(daynight=dn, scan_lo=edges[b], scan_hi=edges[b + 1], scan_mid=g.scan.mean(), n_modis_px=len(g),
            viirs_px_per_modis_mean=g.nv.mean(), viirs_px_per_modis_median=g.nv.median(), viirs_px_per_modis_if_any=w.nv.mean(),
            footprint_area_ratio=(g.scan * g.track).mean() / 0.375**2,
            share_modis_only=(g.nv == 0).mean(), share_modis_only_2xbox=(g.nv2 == 0).mean(), share_modis_only_frp=g[g.nv == 0].mfrp.sum() / g.mfrp.sum(),
            ratio_of_sums_all=g.vfrp.sum() / g.mfrp.sum(), ratio_of_sums_matched=w.vfrp.sum() / w.mfrp.sum(),
            ratio_of_sums_matched_vq=w.vfrpq.sum() / w.mfrp.sum(),
            median_px_ratio=10**lr.median(), p16_px_ratio=10**lr.quantile(.16), p84_px_ratio=10**lr.quantile(.84), modis_frp_median=g.mfrp.median()))
t = pd.DataFrame(rows); t.to_csv(f'{R}/frp_ratio_vs_scan.csv', index=False)
pd.set_option('display.width', 250); print(t.round(3).to_string())
fits = []
for dn in 'DN':
    s = t[t.daynight == dn]
    for col in ['ratio_of_sums_matched', 'ratio_of_sums_all', 'viirs_px_per_modis_mean']:
        cf = np.polyfit(s.scan_mid, s[col], 2, w=np.sqrt(s.n_modis_px))
        res = s[col] - np.polyval(cf, s.scan_mid)
        fits.append(dict(daynight=dn, quantity=col, a0=cf[2], a1=cf[1], a2=cf[0], rms_resid=np.sqrt((res**2).mean())))
f = pd.DataFrame(fits); f.to_csv(f'{R}/frp_ratio_vs_scan_polyfit.csv', index=False); print(f.round(4).to_string())
for dn in 'DN':
    g = d[d.dn == dn]; w = g[g.nv > 0]
    print(dn, 'overall: modis-only share', round((g.nv == 0).mean(), 3), 'ratio_of_sums matched', round(w.vfrp.sum() / w.mfrp.sum(), 3),
          'all', round(g.vfrp.sum() / g.mfrp.sum(), 3), 'modis-only 2x box', round((g.nv2 == 0).mean(), 3),
          'px-level log10 ratio sd', round(np.log10(w.vfrp.clip(lower=.01) / w.mfrp.clip(lower=.01)).std(), 3))
fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
for dn, c in (('D', '#d0443e'), ('N', '#2a6fdb')):
    s = t[t.daynight == dn]; xx = np.linspace(1, 4.8, 100)
    r = f[(f.daynight == dn) & (f.quantity == 'ratio_of_sums_matched')].iloc[0]
    ax[0].fill_between(s.scan_mid, s.p16_px_ratio, s.p84_px_ratio, color=c, alpha=0.12)
    ax[0].plot(s.scan_mid, s.ratio_of_sums_matched, 'o', color=c, label=f'{dn}: ratio of sums (MODIS pixels with VIIRS inside)')
    ax[0].plot(xx, r.a0 + r.a1 * xx + r.a2 * xx**2, '-', color=c, label=f'{dn} fit: {r.a0:.2f} {r.a1:+.2f}s {r.a2:+.3f}s²')
    ax[0].plot(s.scan_mid, s.median_px_ratio, 'x', color=c, label=f'{dn}: median per-pixel ratio (band 16-84%)')
    ax[1].plot(s.scan_mid, s.viirs_px_per_modis_if_any, 'o-', color=c, label=f'{dn}: VIIRS pixels per MODIS pixel (when >=1)')
    ax[1].plot(s.scan_mid, s.share_modis_only * 10, 's--', color=c, alpha=0.7, label=f'{dn}: share MODIS-only pixels x10 (1x box)')
    ax[1].plot(s.scan_mid, s.share_modis_only_2xbox * 10, 'v:', color=c, alpha=0.7, label=f'{dn}: share MODIS-only x10 (2x box)')
ax[0].axhline(1, color='grey', lw=0.7); ax[0].set_yscale('log'); ax[0].set_xlabel('MODIS pixel size along scan (km)'); ax[0].set_ylabel('VIIRS FRP inside footprint / MODIS FRP')
ax[0].set_title('Fire power: VIIRS vs MODIS, same pixel, same 10 min'); ax[0].legend(fontsize=7); ax[0].grid(alpha=0.3, which='both')
ax[1].set_xlabel('MODIS pixel size along scan (km)'); ax[1].set_title('How many VIIRS pixels fall in one MODIS pixel'); ax[1].legend(fontsize=7); ax[1].grid(alpha=0.3)
fig.suptitle('Footprint-scale comparison, Aqua MODIS vs S-NPP VIIRS (2015, 2019, 2021; footprint = scan x track box, E-W)', fontsize=10)
fig.tight_layout(); fig.savefig(f'{R}/fig_frp_ratio_vs_scan.png', dpi=140); print('fig ok')
