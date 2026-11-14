import pandas as pd, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt, numpy as np
w = pd.read_csv('rezultate/calib_physics_ml/p1_weights.csv'); B = ['lt3', '3_6', '6_10', '10_20', '20_50', 'ge50']
lab = ['<3', '3-6', '6-10', '10-20', '20-50', '>=50']
fig, ax = plt.subplots(1, 2, figsize=(10, 4))
for k, var in enumerate(['n', 'frp']):
    for dn, c in (('D', '#d95f02'), ('N', '#1b9e77')):
        g = w[(w['var'] == var) & (w.daynight == dn)]
        a = g[g.region == 'ALL'][B].values[0]; reg = g[~g.region.isin(['ALL', 'OTHR'])][B].values
        x = np.arange(6) + (-0.12 if dn == 'D' else 0.12)
        ax[k].plot(x, a, 'o-', color=c, label=f'{"day" if dn=="D" else "night"} (global)')
        ax[k].vlines(x, reg.min(0), reg.max(0), color=c, alpha=0.4, lw=4, label=f'{dn} range across regions')
        print(var, dn, 'global', np.round(a, 3), 'reg min', np.round(reg.min(0), 3), 'reg max', np.round(reg.max(0), 3))
    ax[k].set_xticks(range(6)); ax[k].set_xticklabels(lab); ax[k].set_xlabel('VIIRS pixel FRP class (MW)')
    ax[k].set_ylabel(['Aqua fire pixels per VIIRS fire pixel', 'Aqua FRP per MW of VIIRS FRP'][k]); ax[k].grid(alpha=.3); ax[k].legend(fontsize=8)
ax[0].set_title('Counts: empirical MODIS "detection efficiency"'); ax[1].set_title('FRP: share of VIIRS FRP MODIS recovers')
fig.suptitle('Fitted on 2012-02..2017-12 (Aqua vs S-NPP, monthly 0.25 deg cells)'); fig.tight_layout()
fig.savefig('rezultate/calib_physics_ml/fig_detection_efficiency.png', dpi=130)
for lab_ in ('P1_frpbin_region', 'CR_B2_region_season'):
    for var in ('n', 'frp'):
        for dn in 'DN':
            try: r = pd.read_csv(f'rezultate/eval/{lab_}_{var}_{dn}_regions.csv')
            except Exception: continue
            print(lab_, var, dn, ' '.join(f'{a}:{b:+.2f}' for a, b in zip(r.region, r.bias)))
