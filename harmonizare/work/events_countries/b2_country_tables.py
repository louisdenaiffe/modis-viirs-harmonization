"""b2: cell -> country lookup (majority of FIRMS detections 2015/2019/2021, MODIS+VIIRS),
nearest-neighbour fill (<=1 deg) for fire cells missing from those years, then country x month table."""
import duckdb, numpy as np, pandas as pd
from scipy.spatial import cKDTree
W, R = 'work/events_countries', 'rezultate/events_countries'
c = duckdb.connect()
c.sql("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='data/_ducktmp/events_countries'")
cc = c.sql(f"""WITH t AS (SELECT ix, iy, country, sum(n) n FROM '{W}/_cc_*.parquet' GROUP BY ALL),
  r AS (SELECT *, sum(n) OVER (PARTITION BY ix, iy) tot,
        row_number() OVER (PARTITION BY ix, iy ORDER BY n DESC, country) rk FROM t)
  SELECT ix, iy, country, (n / tot)::FLOAT AS share, tot::INT AS n_points FROM r WHERE rk = 1""").df()
cc['method'] = 'majority'
fire = c.sql("""SELECT ix, iy, sum(n_eq) n_eq FROM 'rezultate/final/parts/final_*.parquet' GROUP BY ALL""").df()
m = fire.merge(cc[['ix', 'iy', 'country']], on=['ix', 'iy'], how='left')
tot = m.n_eq.sum(); miss = m[m.country.isna()]
print(f"fire cells {len(m)}, without country {len(miss)} ({len(miss)/len(m):.1%} of cells), "
      f"{miss.n_eq.sum()/tot:.2%} of total n_eq")
# nearest assigned cell within 1 deg (4 cells), lon distance scaled by cos(lat)
lat = lambda iy: (iy + 0.5) * 0.25 - 90
def xy(df): return np.c_[df.ix * np.cos(np.radians(lat(df.iy))), df.iy]
tree = cKDTree(xy(cc))
d, k = tree.query(xy(miss), distance_upper_bound=4.0)
ok = np.isfinite(d)
fill = miss[ok][['ix', 'iy']].copy()
fill['country'] = cc.country.values[k[ok]]; fill['share'] = np.nan; fill['n_points'] = 0; fill['method'] = 'nearest<=1deg'
print(f"filled {ok.sum()} cells = {miss.n_eq.values[ok].sum()/tot:.2%} of n_eq; "
      f"still unassigned {(~ok).sum()} cells = {miss.n_eq.values[~ok].sum()/tot:.3%} of n_eq")
out = pd.concat([cc, fill.astype({'share': 'float32'})], ignore_index=True)
out['ix'] = out.ix.astype('int16'); out['iy'] = out.iy.astype('int16')
out['lon'] = ((out.ix + 0.5) * 0.25 - 180).astype('float32'); out['lat'] = lat(out.iy).astype('float32')
out.to_parquet(f'{R}/cell_country.parquet', index=False)
mm = m.merge(out[['ix','iy','share']], on=['ix','iy'], how='left')
mm = mm[mm.country.notna()]
print(f"n_eq-weighted: {(mm.n_eq*(mm.share<0.8)).sum()/mm.n_eq.sum():.1%} of n_eq in border cells with majority share <80%")
# country x month
c.register('cc', out[['ix', 'iy', 'country']])
cm = c.sql("""WITH f AS (SELECT cc.country, f.year, f.month, f.daynight, f.source, sum(f.n_eq) n, sum(f.frp_eq) frp
              FROM 'rezultate/final/parts/final_*.parquet' f JOIN cc USING (ix, iy) GROUP BY ALL)
  SELECT country, year, month, daynight, sum(n) n_eq, sum(frp) frp_eq, arg_max(source, n) AS source FROM f GROUP BY ALL""").df()
allr = cm.groupby(['country', 'year', 'month'], as_index=False).agg(n_eq=('n_eq', 'sum'), frp_eq=('frp_eq', 'sum'))
src = cm.sort_values('n_eq').groupby(['country', 'year', 'month']).source.last().reset_index()
allr = allr.merge(src, on=['country', 'year', 'month']); allr['daynight'] = 'ALL'
cm = pd.concat([cm, allr], ignore_index=True)
# complete grid (zeros for months without detections), 2000-11 .. 2025-12
ym = c.sql("SELECT DISTINCT year, month, arg_max(source, n_eq) OVER (PARTITION BY year, month) AS gsrc FROM 'rezultate/final/parts/final_*.parquet'").df()
ym = ym.groupby(['year','month'], as_index=False).gsrc.first()
grid = pd.MultiIndex.from_product([cm.country.unique(), ['D', 'N', 'ALL']], names=['country', 'daynight']).to_frame(index=False)
grid = grid.merge(ym, how='cross')
cm = grid.merge(cm, on=['country', 'daynight', 'year', 'month'], how='left')
cm['source'] = cm.source.fillna(cm.gsrc); cm = cm.drop(columns='gsrc')
cm[['n_eq', 'frp_eq']] = cm[['n_eq', 'frp_eq']].fillna(0)
ref = cm.year.between(2003, 2025)
for v in ['n', 'frp']:
    cm[f'pct_rank_{v}'] = np.nan
    cm.loc[ref, f'pct_rank_{v}'] = cm[ref].groupby(['country', 'daynight', 'month'])[f'{v}_eq'].rank(method='max', pct=False)
    nref = cm[ref].groupby(['country', 'daynight', 'month'])[f'{v}_eq'].transform('size')
    # share of reference years (2003-2025) with a value <= this one; 1.0 = record month
    cm.loc[ref, f'pct_rank_{v}'] = (cm.loc[ref, f'pct_rank_{v}'] / nref).round(4)
cm['n_eq'] = cm.n_eq.round(1); cm['frp_eq'] = cm.frp_eq.round(1)
cm = cm.sort_values(['country', 'daynight', 'year', 'month'])[
    ['country', 'daynight', 'year', 'month', 'n_eq', 'frp_eq', 'source', 'pct_rank_n', 'pct_rank_frp']]
cm.to_csv(f'{R}/country_month.csv', index=False)
print(len(cm), 'rows,', cm.country.nunique(), 'countries')
