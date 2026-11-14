"""08_app_package.py — put everything the web app needs into harmonizare/APP_DATA/ (run after 04_build_final.py).
Run from project folder: python3 harmonizare/scripts/08_app_package.py"""
import duckdb, pandas as pd, numpy as np, sys, os, shutil, glob
R = 'harmonizare'; F = f'{R}/rezultate/final'; A = f'{R}/APP_DATA'
sys.path.insert(0, f'{R}/scripts'); import eval_common as ec
os.makedirs(f'{A}/cells_monthly', exist_ok=True)
for f in glob.glob(f'{F}/parts/final_*.parquet'): shutil.copyfile(f, f'{A}/cells_monthly/' + os.path.basename(f))
con = duckdb.connect(); con.execute("SET memory_limit='900MB'; SET threads=2")
cc = pd.read_parquet(f'{R}/rezultate/events_countries/cell_country.parquet')[['ix', 'iy', 'country']]
cells = pd.DataFrame({'ix': np.repeat(np.arange(1440), 720), 'iy': np.tile(np.arange(720), 1440)})
cells['region'] = ec.region_of(cells.ix.values, cells.iy.values).astype(str)
cells = cells.merge(cc, on=['ix', 'iy'], how='left'); cells['country'] = cells.country.fillna('unassigned'); con.register('cells', cells)
acc = {'modis': pd.read_csv(f'{R}/rezultate/calib_physics_ml/accuracy_modis_scale.csv'), 'viirs': pd.read_csv(f'{R}/rezultate/calib_ratio/accuracy_viirs_scale.csv')}
EDGES = {'1-9': 1, '10-99': 10, '100-999': 100, '1000-9999': 1000, '>=10000': 10000}
def typical_err(scale, dn, n):
    """median absolute % error of a converted monthly value, from the 1-degree accuracy lookup (bins on the predicted count)"""
    t = acc[scale]; t = t[(t['agg'] == 'monthly') & (t.scale_deg == 1) & (t['var'] == 'n') & (t.daynight == dn) & t.activity_bin.isin(EDGES)]
    t = t.assign(lo=t.activity_bin.map(EDGES)).sort_values('lo'); out = np.full(len(n), np.nan)
    for lo, e in zip(t.lo, t.median_abs_pct_err): out[np.asarray(n) >= lo] = e
    return out
def table(unit):
    d = con.execute(f"""SELECT {unit}, daynight, year, month, sum(n_eq) n_modis, sum(frp_eq) frp_modis, sum(n_veq) n_viirs, sum(frp_veq) frp_viirs,
        any_value(source) AS source_modis, any_value(source_v) AS source_viirs, any_value(flag) AS flag
        FROM read_parquet('{F}/parts/final_*.parquet') JOIN cells USING (ix, iy) GROUP BY ALL""").df()
    if unit == 'region':
        g = d[d.region != 'OTHR'].groupby(['daynight', 'year', 'month']).agg(n_modis=('n_modis', 'sum'), frp_modis=('frp_modis', 'sum'), n_viirs=('n_viirs', 'sum'),
            frp_viirs=('frp_viirs', 'sum'), source_modis=('source_modis', 'first'), source_viirs=('source_viirs', 'first'), flag=('flag', 'first')).reset_index().assign(region='GLOBAL')
        d = pd.concat([d, g], ignore_index=True)
    a = d.groupby([unit, 'year', 'month']).agg(n_modis=('n_modis', 'sum'), frp_modis=('frp_modis', 'sum'), n_viirs=('n_viirs', 'sum'), frp_viirs=('frp_viirs', 'sum'),
        source_modis=('source_modis', 'first'), source_viirs=('source_viirs', 'first'), flag=('flag', 'first')).reset_index().assign(daynight='ALL')
    d = pd.concat([d, a], ignore_index=True)
    ok = d.year >= 2003; gk = [unit, 'daynight', 'month']
    for sc in ('modis', 'viirs'):
        d.loc[ok, f'rank_{sc}'] = d[ok].groupby(gk)[f'n_{sc}'].rank(ascending=False, method='min')      # 1 = most fire for this calendar month since 2003
        d.loc[ok, f'pct_rank_{sc}'] = d[ok].groupby(gk)[f'n_{sc}'].rank(pct=True)
        d[f'typ_err_pct_{sc}'] = 0.0
    d.loc[ok, 'n_years'] = d[ok].groupby(gk).year.transform('count')
    for dn in ('D', 'N', 'ALL'):
        m = d.daynight == dn
        mm = m & (d.source_modis != 'aqua'); d.loc[mm, 'typ_err_pct_modis'] = typical_err('modis', dn, d.loc[mm, 'n_modis'].values)
        mv = m & (d.source_viirs != 'viirs'); d.loc[mv, 'typ_err_pct_viirs'] = typical_err('viirs', dn, d.loc[mv, 'n_viirs'].values)
    d['confidence'] = np.select([d.n_modis >= 1000, d.n_modis >= 100, d.n_modis >= 10], ['high', 'medium', 'low'], 'none')
    return d.sort_values([unit, 'daynight', 'year', 'month']).round(3)
for unit in ('country', 'region'):
    t = table(unit); t.to_csv(f'{A}/{unit}_month.csv', index=False); print(unit, len(t), t[unit].nunique())
for src, dst in ((f'{R}/rezultate/calib_physics_ml/accuracy_modis_scale.csv', 'accuracy_modis_scale.csv'), (f'{R}/rezultate/calib_ratio/accuracy_viirs_scale.csv', 'accuracy_viirs_scale.csv'),
                 (f'{R}/rezultate/events_countries/cell_country.parquet', 'cell_country.parquet'), (f'{R}/rezultate/events_countries/famous_fires.csv', 'famous_fires.csv'),
                 (f'{F}/validation_by_country.csv', 'validation_by_country.csv'), (f'{F}/fig_harmonization_summary.png', 'fig_harmonization_summary.png'),
                 (f'{R}/rezultate/simul_overpass/fig_detection_curve.png', 'fig_detection_curve.png'), (f'{R}/rezultate/static_mask/cell_static_share.parquet', 'cell_static_share.parquet')):
    if os.path.exists(src): shutil.copyfile(src, f'{A}/{dst}')
c = pd.read_csv(f'{A}/country_month.csv'); x = c[(c.country == 'Romania') & (c.daynight == 'ALL') & (c.month == 3) & c.year.isin([2005, 2012, 2022])]
print(x[['year', 'n_modis', 'n_viirs', 'source_modis', 'source_viirs', 'rank_modis', 'rank_viirs', 'typ_err_pct_modis', 'typ_err_pct_viirs', 'confidence']].to_string(index=False))
g = pd.read_csv(f'{A}/region_month.csv'); g = g[(g.region == 'GLOBAL') & (g.daynight == 'ALL')].groupby('year')[['n_modis', 'n_viirs']].sum(); print((g / 1e6).round(2).T.to_string())
