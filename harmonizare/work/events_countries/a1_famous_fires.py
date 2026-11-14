"""a1: famous-fires sanity test. For each documented event (box or country, months) sum the harmonized
record (day+night) and rank the event's peak month against the same calendar month 2003-2025 and against
all 276 months 2003-2025. Same for the naive record (Aqua n_sum to 2011 [Terra before 2002-07], raw S-NPP n_sum from 2012)."""
import duckdb, numpy as np, pandas as pd
R = 'rezultate/events_countries'
WP = 'https://en.wikipedia.org/wiki/'
# id, label, kind(event/control), lon0, lon1, lat0, lat1 (or country:), year, months, source url
E = [
 ('GR07', 'Greece Peloponnese fires', 'event', 21.0, 23.5, 36.5, 38.5, 2007, [8], WP+'2007_Greek_forest_fires'),
 ('BAL07', 'Balkans heatwave fires (MK/BG/AL/RS)', 'event', 19.5, 28.0, 40.7, 44.0, 2007, [7], 'https://science.nasa.gov/earth/earth-observatory/fires-on-the-balkan-peninsula-7898/'),
 ('AU09', 'Black Saturday, Victoria', 'event', 144.0, 147.5, -38.8, -36.5, 2009, [2], WP+'Black_Saturday_bushfires'),
 ('RU10', 'Western Russia fires', 'event', 36.0, 50.0, 52.0, 58.0, 2010, [7, 8], WP+'2010_Russian_wildfires'),
 ('ID15', 'Indonesia peat fires (Sumatra+Kalimantan)', 'event', 95.0, 119.0, -6.0, 4.0, 2015, [9, 10], WP+'2015_Southeast_Asian_haze'),
 ('CA16', 'Fort McMurray, Alberta', 'event', -113.0, -109.5, 55.5, 58.0, 2016, [5], 'https://wikiwand.com/en/articles/2016_Fort_McMurray_wildfire'),
 ('CL17', 'Chile central-south fires', 'event', -73.5, -70.5, -37.5, -33.5, 2017, [1, 2], WP+'2017_Chile_wildfires'),
 ('PT17a', 'Portugal Pedrogao Grande', 'event', -8.8, -7.5, 39.5, 40.5, 2017, [6], WP+'June_2017_Portugal_wildfires'),
 ('PT17b', 'Portugal/Galicia 15 Oct fires', 'event', -9.0, -6.5, 39.5, 42.5, 2017, [10], 'https://www.safecommunitiesportugal.com/wp-content/uploads/2022/10/2022-Five-years-on-October-2017-fires.-.pdf'),
 ('AM19', 'Brazilian Amazon fires', 'event', -70.0, -45.0, -13.0, 0.0, 2019, [8], 'https://www.esa.int/ESA_Multimedia/Images/2019/08/Number_of_wildfires_in_the_Amazon'),
 ('BO19', 'Bolivia Chiquitania fires', 'event', -69.0, -57.5, -20.0, -10.0, 2019, [8, 9], 'https://reliefweb.int/disaster/wf-2019-000096-bol'),
 ('ID19', 'Indonesia fires/haze', 'event', 95.0, 119.0, -6.0, 4.0, 2019, [9], WP+'2019_Southeast_Asian_haze'),
 ('AU19', 'Black Summer, SE Australia', 'event', 145.0, 154.0, -38.5, -28.0, 2019, [12, 13], WP+'2019%E2%80%9320_Australian_bushfire_season'),
 ('US20', 'California Aug-Sep fires', 'event', -124.5, -119.0, 35.0, 42.0, 2020, [8, 9], WP+'August_Complex_fire'),
 ('TR21', 'SW Turkey fires (Manavgat, Marmaris)', 'event', 27.0, 33.0, 36.0, 38.0, 2021, [7, 8], 'https://earthobservatory.nasa.gov/images/148650/fires-rage-in-turkey'),
 ('GR21', 'Greece Evia/Attica/Peloponnese', 'event', 21.0, 24.5, 36.5, 39.2, 2021, [8], 'https://earthobservatory.nasa.gov/images/148682/fire-consumes-large-swaths-of-greece'),
 ('DZ21', 'Algeria Kabylie fires', 'event', 3.0, 8.5, 35.8, 37.2, 2021, [8], 'https://www.aljazeera.com/gallery/2021/8/11/dozens-dead-as-wildfires-rip-through-northern-algeria'),
 ('SA21', 'Yakutia/Sakha record season', 'event', 105.0, 160.0, 56.0, 72.0, 2021, [6, 7, 8], 'https://earthobservatory.nasa.gov/images/148943/a-record-breaking-year-for-fire-in-sakha'),
 ('RO22', 'Romania spring 2022 (7x more forest fires, Romsilva)', 'event', 'country:Romania', None, None, None, 2022, [3], 'https://www.romania-insider.com/society/romania-sevenfold-increase-vegetation-fires-2022'),
 ('CL23', 'Chile Nuble/Biobio/Araucania', 'event', -74.0, -71.0, -39.0, -35.5, 2023, [2], 'https://earthobservatory.nasa.gov/images/150994/fires-scar-the-chilean-landscape'),
 ('CA23', 'Canada record season', 'event', 'country:Canada', None, None, None, 2023, [5, 6, 7, 8, 9], WP+'2023_Canadian_wildfires'),
 ('HI23', 'Maui / Lahaina', 'event', -156.8, -155.9, 20.5, 21.1, 2023, [8], 'https://lessons.wildfire.gov/incident/maui-wildfires-2023'),
 ('GR23', 'Evros / Dadia (largest EU fire)', 'event', 25.5, 26.7, 40.7, 41.6, 2023, [8], 'https://www.cbsnews.com/news/greece-europe-battling-largest-wildfire-ever-recorded-out-of-control'),
 ('CL24', 'Chile Valparaiso / Vina del Mar', 'event', -71.8, -71.0, -33.4, -32.8, 2024, [2], 'https://earthobservatory.nasa.gov/images/152417/inferno-scars-valparaiso'),
 ('AM24', 'Brazilian Amazon 2024 drought fires', 'event', -70.0, -45.0, -13.0, 0.0, 2024, [8, 9], WP+'2024_Brazil_wildfires'),
 ('BO24', 'Bolivia record 2024 season', 'event', -69.0, -57.5, -20.0, -10.0, 2024, [8, 9], 'https://ctif.org/news/10-million-hectares-forested-land-burned-bolivia-2024-so-far'),
 ('US25', 'Los Angeles Palisades/Eaton', 'event', -118.9, -117.9, 33.9, 34.4, 2025, [1], 'https://www.wikiwand.com/simple/articles/January_2025_Southern_California_wildfires'),
 ('KR25', 'South Korea Uiseong/Andong', 'event', 128.0, 129.7, 35.9, 36.9, 2025, [3], 'https://www.pbs.org/newshour/world/wildfires-ravaging-southern-south-korea-leave-24-dead-force-thousands-to-evacuate'),
 ('JP25', 'Japan Ofunato (2,900 ha)', 'event', 141.5, 142.0, 38.9, 39.2, 2025, [2, 3], 'https://www.voanews.com/a/japan-s-worst-wildfire-in-half-a-century-spreads/7996352.html'),
 ('RO25', 'Romania 2025 (126k ha, EFFIS; month not given)', 'event', 'country:Romania', None, None, None, 2025, list(range(1, 13)), 'https://www.romania-insider.com/index%2ephp/wildfires-eu-2025-romania-third-most-affected'),
 # quiet controls (same boxes, years without a documented major episode / wet years)
 ('cGR14', 'CONTROL Greece Peloponnese Aug 2014', 'control', 21.0, 23.5, 36.5, 38.5, 2014, [8], ''),
 ('cRU13', 'CONTROL Western Russia Jul-Aug 2013', 'control', 36.0, 50.0, 52.0, 58.0, 2013, [7, 8], ''),
 ('cAU11', 'CONTROL Victoria Feb 2011 (La Nina, wet)', 'control', 144.0, 147.5, -38.8, -36.5, 2011, [2], ''),
 ('cID10', 'CONTROL Indonesia Sep-Oct 2010 (La Nina, wet)', 'control', 95.0, 119.0, -6.0, 4.0, 2010, [9, 10], ''),
 ('cID22', 'CONTROL Indonesia Sep-Oct 2022 (La Nina, wet)', 'control', 95.0, 119.0, -6.0, 4.0, 2022, [9, 10], ''),
 ('cCA20', 'CONTROL Canada May-Sep 2020', 'control', 'country:Canada', None, None, None, 2020, [5, 6, 7, 8, 9], ''),
]
c = duckdb.connect()
c.sql("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='data/_ducktmp/events_countries'")
cc = pd.read_parquet(f'{R}/cell_country.parquet')
cells = []
for e in E:
    eid, lo0 = e[0], e[3]
    if isinstance(lo0, str):
        s = cc[cc.country == lo0.split(':')[1]][['ix', 'iy']].copy()
    else:
        lo1, la0, la1 = e[4], e[5], e[6]
        ix = np.arange(int(np.floor((lo0 + 180) / .25)), int(np.floor((lo1 + 180) / .25)) + 1)
        iy = np.arange(int(np.floor((la0 + 90) / .25)), int(np.floor((la1 + 90) / .25)) + 1)
        s = pd.DataFrame([(a, b) for a in ix for b in iy], columns=['ix', 'iy'])
    s['eid'] = eid; cells.append(s)
cells = pd.concat(cells); cells[['ix', 'iy']] = cells[['ix', 'iy']].astype('int16')
c.register('cells', cells)
h = c.sql("""SELECT eid, year, month, sum(n_eq) n, sum(frp_eq) frp, arg_max(source, n_eq) src
  FROM 'rezultate/final/parts/final_*.parquet' JOIN cells USING (ix, iy) WHERE year >= 2003 GROUP BY ALL""").df()
nv = c.sql("""SELECT eid, year, month, sum(n_sum) n_naive FROM 'data/grid/monthly_025/monthly_*.parquet' JOIN cells USING (ix, iy)
  WHERE year >= 2003 AND ((year <= 2011 AND satellite = 'Aqua') OR (year >= 2012 AND satellite = 'SNPP')) GROUP BY ALL""").df()
ym = pd.DataFrame([(y, m) for y in range(2003, 2026) for m in range(1, 13)], columns=['year', 'month'])
rows = []
for e in E:
    eid, label, kind, year, months, url = e[0], e[1], e[2], e[7], e[8], e[9]
    d = ym.merge(h[h.eid == eid], on=['year', 'month'], how='left').merge(nv[nv.eid == eid], on=['year', 'month', 'eid'], how='left')
    d[['n', 'frp', 'n_naive']] = d[['n', 'frp', 'n_naive']].fillna(0)
    for v in ['n', 'frp', 'n_naive']:
        d[f'rk_m_{v}'] = d.groupby('month')[v].rank(ascending=False, method='min')
        d[f'rk_all_{v}'] = d[v].rank(ascending=False, method='min')
    # event months (month 13 = January of next year)
    em = [(year + (m - 1) // 12, (m - 1) % 12 + 1) for m in months]
    w = d[[ (y, m) in em for y, m in zip(d.year, d.month)]]
    pk = w.loc[w.n.idxmax()]
    pkn = w.loc[w.n_naive.idxmax()]
    cal = d[d.month == pk.month]
    rows.append(dict(event_id=eid, event=label, kind=kind, window=f"{em[0][0]}-{em[0][1]:02d}..{em[-1][0]}-{em[-1][1]:02d}",
        n_cells=int((cells.eid == eid).sum()), n_eq_window=round(w.n.sum()), frp_eq_window=round(w.frp.sum()),
        peak_month=f"{int(pk.year)}-{int(pk.month):02d}", source_peak=pk.src, n_eq_peak=round(pk.n), frp_eq_peak=round(pk.frp),
        ratio_to_median_same_month=round(pk.n / max(cal.n.median(), 1), 1),
        rank_same_month_n=int(pk.rk_m_n), rank_same_month_frp=int(pk.rk_m_frp), n_years=23,
        pct_rank_n=round(1 - (pk.rk_m_n - 1) / 23, 3),
        rank_all_months_n=int(pk.rk_all_n), rank_all_months_frp=int(pk.rk_all_frp), n_months=276,
        top5_same_month=bool(min(pk.rk_m_n, pk.rk_m_frp) <= 1), top10_same_month=bool(min(pk.rk_m_n, pk.rk_m_frp) <= 2),
        top5_all_months=bool(min(pk.rk_all_n, pk.rk_all_frp) <= 13),
        naive_n_peak=round(pkn.n_naive), naive_rank_same_month=int(pkn.rk_m_n_naive), naive_rank_all_months=int(pkn.rk_all_n_naive),
        naive_top10_same_month=bool(pkn.rk_m_n_naive <= 2),
        viirs_era_years_above_harm=int(((cal.year >= 2012) & (cal.n > pk.n)).sum()),
        viirs_era_years_above_naive=int(((cal.year >= 2012) & (cal.n_naive > pk.n_naive)).sum()),
        top2_slots_post2012_harm=int((cal.nlargest(2, 'n').year >= 2012).sum()),
        top2_slots_post2012_naive=int((cal.nlargest(2, 'n_naive').year >= 2012).sum()),
        source_url=url))
out = pd.DataFrame(rows)
out.to_csv(f'{R}/famous_fires.csv', index=False)
pd.set_option('display.width', 250)
print(out[['event_id','peak_month','source_peak','n_eq_peak','rank_same_month_n','rank_same_month_frp','rank_all_months_n','naive_rank_same_month','naive_rank_all_months','viirs_era_years_above_harm','viirs_era_years_above_naive','top2_slots_post2012_harm','top2_slots_post2012_naive']].to_string())
ev = out[out.kind == 'event']
print('top2 slots held by 2012+ years: harm', ev.top2_slots_post2012_harm.sum(), 'naive', ev.top2_slots_post2012_naive.sum(), 'of', 2*len(ev), '(chance 14/23 =', round(2*len(ev)*14/23), ')')
