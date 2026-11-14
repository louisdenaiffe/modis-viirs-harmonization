"""Empirical outage calendar + monthly completeness from daily global detection counts (all detections, UTC acq_date).
A day is flagged when its count < THR x baseline, baseline = median of non-zero days in +-15 days. For satellites with an
overlapping partner, the flag must be confirmed by the ratio to the partner (ratio < THR x its +-15-day median), so a
globally quiet fire day (seen by every sensor) is not an outage. Zero days are always flagged."""
import pandas as pd, numpy as np, os
R = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')); OUT = f'{R}/rezultate/qc_stability'
THR = 0.5; THR_DN = 0.3  # stricter for day-only / night-only series (night counts are small and noisy)
d = pd.read_parquet(f'{R}/work/qc_stability/daily_all.parquet'); d['acq_date'] = pd.to_datetime(d.acq_date)
span = {'Terra': ('2000-11-01', '2025-12-31'), 'Aqua': ('2002-07-04', '2025-12-31'), 'SNPP': ('2012-01-20', '2025-12-31')}
refs = {'Terra': ['Aqua', 'SNPP'], 'Aqua': ['Terra', 'SNPP'], 'SNPP': ['Aqua', 'Terra']}
def series(sat, dn):
    x = d[d.satellite == sat] if dn == 'DN' else d[(d.satellite == sat) & (d.daynight == dn)]
    x = x.groupby('acq_date').n.sum(); idx = pd.date_range(*span[sat]); return x.reindex(idx, fill_value=0).astype(float)
def rmed(x):  # robust baseline: max of +-15-day and +-30-day medians of non-zero days (a long outage cannot drag it down)
    z = x.replace(0, np.nan)
    return np.fmax(z.rolling(31, center=True, min_periods=8).median(), z.rolling(61, center=True, min_periods=15).median())
rows, flags = [], {}
for sat in span:
    for dn in ('DN', 'D', 'N'):
        thr = THR if dn == 'DN' else THR_DN
        x = series(sat, dn); base = rmed(x)
        rel = x / base; low = rel < thr
        conf = pd.Series(False, index=x.index); has_ref = pd.Series(False, index=x.index)
        for rf in refs[sat]:
            y = series(rf, dn).reindex(x.index, fill_value=0)
            ok = y > 0.3 * y.replace(0, np.nan).rolling(31, center=True, min_periods=8).median()  # partner normal
            r = (x / y).where(ok); rb = rmed(r)
            has_ref |= ok & rb.notna(); conf |= (r < thr * rb)
        flag = (x == 0) | (low & (conf | ~has_ref))
        flags[(sat, dn)] = pd.DataFrame({'n': x, 'base': base, 'rel': rel.clip(upper=1).fillna(1).where(x > 0, 0), 'flag': flag})
        # merge flagged days into periods (allow 1-day gap)
        f = flag[flag].index
        if len(f) == 0: continue
        grp = (pd.Series(f).diff().dt.days.fillna(99) > 2).cumsum()
        for _, g in pd.Series(f).groupby(grp.values):
            s, e = g.iloc[0], g.iloc[-1]; seg = flags[(sat, dn)].loc[s:e]
            nz = (seg.n == 0).sum()
            kind = 'no_data' if nz == len(seg) else ('mostly_no_data' if nz > len(seg) / 2 else 'partial_low')
            rows.append(dict(satellite=sat, daynight=dn, start_date=s.date(), end_date=e.date(), ndays=(e - s).days + 1,
                             kind=kind, evidence=f"zero-count days {nz}/{len(seg)}; mean count/baseline {seg.rel.mean():.2f}; "
                             f"baseline~{seg.base.mean():.0f}/day"))
cal = pd.DataFrame(rows)
# keep D/N-specific periods only when not already inside a DN (whole-satellite) period
dnp = cal[cal.daynight == 'DN']
def covered(r):
    s = dnp[(dnp.satellite == r.satellite)]; return ((s.start_date <= r.start_date) & (s.end_date >= r.end_date)).any()
cal = cal[(cal.daynight == 'DN') | ~cal.apply(covered, axis=1)]
cal['daynight'] = cal.daynight.replace({'DN': 'both'})
# known outages (CONTEXT.md)
known = [('Terra', '2001-06-15', '2001-07-02'), ('Terra', '2016-02-19', '2016-02-27'), ('Terra', '2022-10-10', '2022-10-19'),
         ('Aqua', '2020-08-16', '2020-09-02'), ('SNPP', '2022-07-26', '2022-08-20')]
def match(r):
    for k, (s, a, b) in enumerate(known):
        if s == r.satellite and pd.Timestamp(r.start_date) <= pd.Timestamp(b) and pd.Timestamp(r.end_date) >= pd.Timestamp(a): return f'known#{k}'
    return 'NOT_LISTED'
cal['listed'] = cal.apply(match, axis=1)
cal = cal.sort_values(['satellite', 'start_date']); cal.to_csv(f'{OUT}/outage_calendar.csv', index=False)
print(cal[cal.ndays >= 3].to_string())
print('total flagged periods', len(cal), 'of which >=3 days', (cal.ndays >= 3).sum())
for k, (s, a, b) in enumerate(known):
    m = cal[cal.listed == f'known#{k}']; print('KNOWN', s, a, b, '->', m[['daynight','start_date', 'end_date', 'kind']].values.tolist())
# completeness: per satellite x daynight x month. frac_days_ok = share of days not flagged (whole-satellite or own D/N flag);
# coverage = mean over days of min(1, count/baseline) on flagged days, 1 on normal days  (use to rescale)
comp = []
for sat in span:
    fdn = flags[(sat, 'DN')].flag
    for dn in ('D', 'N'):
        t = flags[(sat, dn)].copy(); t['bad'] = t.flag | fdn
        t['cov'] = np.where(t.bad, np.minimum(1, flags[(sat, 'DN')].rel), 1.0)
        g = t.groupby([t.index.year, t.index.month]).agg(days=('bad', 'size'), days_bad=('bad', 'sum'), coverage=('cov', 'mean'))
        g.index.names = ['year', 'month']; g = g.reset_index(); g['satellite'] = sat; g['daynight'] = dn
        g['frac_days_ok'] = 1 - g.days_bad / g.days; comp.append(g)
comp = pd.concat(comp)
comp['ndays_cal'] = pd.to_datetime(dict(year=comp.year, month=comp.month, day=1)).dt.days_in_month
comp['frac_days_ok'] = (comp.days - comp.days_bad) / comp.ndays_cal  # partial first months (mission start) count as incomplete
comp['coverage'] = comp.coverage * comp.days / comp.ndays_cal
comp['flag_month'] = np.where(comp.frac_days_ok < 0.8, 'exclude', np.where(comp.frac_days_ok < 0.97, 'rescale', 'ok'))
comp = comp[['satellite', 'daynight', 'year', 'month', 'ndays_cal', 'days_bad', 'frac_days_ok', 'coverage', 'flag_month']].round(4)
comp.to_csv(f'{OUT}/completeness_monthly.csv', index=False)
print(comp[comp.flag_month != 'ok'].groupby(['satellite', 'daynight', 'flag_month']).size())
print(comp[comp.flag_month == 'exclude'].to_string())
