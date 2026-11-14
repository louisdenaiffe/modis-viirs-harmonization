"""fig_static_map.png: (top) masked core cells by reason; (bottom) 0.25 deg cells where >=50% of SNPP night default-filter detections are static."""
import pandas as pd, numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt, sys
sys.path.insert(0, '.'); M = __import__('04_mask')
OUT = '../../rezultate/static_mask'
m = M.build(D=16, M=9, Y=2, tmin=3, mflag=6, nsmin=0.9, M2=4, Y2=1, spread=2, buf=1, eruptions=True); m = m[m.core]
m['lon'] = (m.sx + .5) * .01 - 180; m['lat'] = (m.sy + .5) * .01 - 90
s = pd.read_parquet(f'{OUT}/cell_static_share.parquet'); s = s[(s.satellite == 'SNPP') & (s.daynight == 'N') & (s.n_total >= 10)]
s['lon'] = (s.ix + .5) * .25 - 180; s['lat'] = (s.iy + .5) * .25 - 90
fig, ax = plt.subplots(2, 1, figsize=(12, 11))
col = {'type_flag_viirs': '#2a6fdb', 'type_flag_modis': '#14a37f', 'persistence': '#e07b00', 'volcano': '#c8102e', 'offshore': '#7b3fa0'}
for r, g in m.groupby('reason'):
    ax[0].scatter(g.lon, g.lat, s=2, c=col[r], label=f'{r} ({len(g):,} cells)'); print('panel1', r, len(g))
ax[0].legend(markerscale=5, loc='lower left'); ax[0].set_title('Static-source mask: core 0.01° cells by reason (2015, 2019, 2021; mask also adds 1-cell buffer)')
for lo, hi, cc in [(0.5, 0.8, '#f4a259'), (0.8, 1.01, '#bc4b51')]:
    g = s[(s.static_share_n >= lo) & (s.static_share_n < hi)]
    ax[1].scatter(g.lon, g.lat, s=3, c=cc, label=f'static share {lo:.0%}-{min(hi,1):.0%}: {len(g):,} cells'); print('panel2', lo, hi, len(g))
g = s[s.static_share_n < 0.5]; print('panel2 <0.5 (grey)', len(g))
ax[1].scatter(g.lon, g.lat, s=1, c='#cccccc', label=f'static share <50%: {len(g):,} cells', zorder=0)
ax[1].legend(markerscale=5, loc='lower left'); ax[1].set_title('S-NPP VIIRS night, 0.25° cells with >=10 detections: share of default-filter detections inside the mask')
for a in ax: a.set_xlim(-180, 180); a.set_ylim(-60, 80); a.set_xlabel('lon'); a.set_ylabel('lat'); a.grid(alpha=.3)
plt.tight_layout(); plt.savefig(f'{OUT}/fig_static_map.png', dpi=110)
