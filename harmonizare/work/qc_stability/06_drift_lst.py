"""drift_by_year.csv: median local solar time per satellite x year x daynight x lat band x hemisphere (type 0, from pass1).
'pooled_approx' rows = detection-weighted mean of the two hemisphere medians (approximation, not an exact pooled median)."""
import duckdb, pandas as pd, os
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
R = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')); OUT = f'{R}/rezultate/qc_stability'
d = duckdb.sql(f"select * from '{R}/work/qc_stability/pass1/*_lst.parquet'").df()
d = d[~((d.satellite == 'SNPP') & (d.yr == 2012) & False)]
p = d.assign(w=d.lst_med * d.n).groupby(['satellite', 'daynight', 'yr', 'band'], as_index=False).agg(w=('w', 'sum'), n=('n', 'sum'))
p['lst_med'] = p.w / p.n; p['hemi'] = 'pooled_approx'; p = p.drop(columns='w')
out = pd.concat([d, p]).sort_values(['satellite', 'daynight', 'band', 'hemi', 'yr'])
out['lst_hhmm'] = out.lst_med.map(lambda h: f'{int(h):02d}:{int(round((h % 1) * 60)) % 60:02d}')
out.round(4).to_csv(f'{OUT}/drift_by_year.csv', index=False)
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
for j, dn in enumerate('DN'):
    for (s, b), g in p[p.daynight == dn].groupby(['satellite', 'band']):
        ax[j].plot(g.yr, g.lst_med, label=f'{s} {b}', ls={'tropics': '-', 'mid_23-50': '--', 'high_50+': ':'}[b],
                   color={'Aqua': '#2a6fdb', 'Terra': '#d9822b', 'SNPP': '#6b8e23'}[s])
    ax[j].set_title('day' if dn == 'D' else 'night'); ax[j].set_ylabel('median local solar time (h)')
ax[0].legend(fontsize=7); fig.suptitle('Overpass time drift (median LST of type-0 detections)'); fig.tight_layout()
fig.savefig(f'{OUT}/fig_drift.png', dpi=110)
t = p[(p.band == 'tropics')].pivot_table(index='yr', columns=['satellite', 'daynight'], values='lst_med')
print(t.loc[[2003, 2012, 2018, 2021, 2022, 2023, 2024, 2025]].round(2).to_string())
h = p[(p.band == 'high_50+') & (p.daynight == 'D')].pivot_table(index='yr', columns='satellite', values='lst_med')
print(h.loc[[2012, 2021, 2025]].round(2).to_string())
