"""Step 5: how much S-NPP activity is below Aqua detectability, and which FRP floor on S-NPP clusters mimics Aqua (tolerant 2x-box match)."""
import sys, os, glob; sys.path.insert(0, os.path.dirname(__file__)); from common import *
import numpy as np, pandas as pd
h = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{W}/s3/hist_*.parquet'))]); h = h[h.lbin > -9]
rows = []
for dn in 'DN':
    g = h[h.dn == dn].groupby('lbin')[['ncl', 'npix', 'frp', 'det_tol', 'frp_det_tol', 'npix_det_tol', 'det_q', 'frp_det_q']].sum().sort_index()
    T = g.sum()
    for F in [0] + [round(10**(k/10), 2) for k in range(3, 18)]:  # floors at the 0.1-dex bin edges
        a = g[g.index >= np.log10(F) - 0.01] if F > 0 else g
        # classification: cluster kept iff FRP >= F; truth = detected (tol)
        tp = a.det_tol.sum(); fp = a.ncl.sum() - tp; fn = T.det_tol - tp
        rows.append(dict(daynight=dn, floor_MW=F, clusters_kept_over_detected=a.ncl.sum() / T.det_tol,
            frp_kept_over_detected_frp=a.frp.sum() / T.frp_det_tol, share_viirs_clusters_kept=a.ncl.sum() / T.ncl,
            share_viirs_frp_kept=a.frp.sum() / T.frp, share_viirs_pixels_kept=a.npix.sum() / T.npix,
            recall=tp / T.det_tol, precision=tp / a.ncl.sum(), f1=2 * tp / (2 * tp + fp + fn)))
    print(dn, 'below-detectability (not detected, tol): clusters', round(1 - T.det_tol / T.ncl, 3), 'pixels', round(1 - T.npix_det_tol / T.npix, 3),
          'FRP', round(1 - T.frp_det_tol / T.frp, 3), '| strict: clusters', round(1 - T.det_q / T.ncl, 3), 'FRP', round(1 - T.frp_det_q / T.frp, 3))
t = pd.DataFrame(rows); t.to_csv(f'{R}/viirs_frp_floor.csv', index=False); pd.set_option('display.width', 250); print(t.round(3).to_string())
