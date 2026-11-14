"""Static-source mask rules. build(...) -> DataFrame(sx,sy,reason); removal(m) -> removed default-filter detections per satellite.
R1 type flag : cell has >= tmin FIRMS type 1/2/3 detections (all sensors, 2015+2019+2021). Volcano (type 1 dominant) always;
               static land/offshore only if those flags span >= mflag distinct calendar months (union over years) -> protects
               seasonal fires that FIRMS itself mislabels (e.g. MODIS type 2 on Indonesian peat, Sep-Oct 2015).
R2b (optional, nsmin): >= D days, >= M2 months, >= spread months in BOTH Jan-Jun and Jul-Dec, night share >= nsmin, in >= Y2 years.
R2 persistence: type-0 non-low detections on >= D distinct days AND in >= M distinct calendar months in one satellite-year,
               in >= Y of the 3 years (any satellite).
R3 (eruptions=True): cells with type-0 detections on >= 2 days inside the box of a known eruption of that year (list ERUPTIONS).
Buffer: every masked core cell + its 8 neighbours (buf=1)."""
import duckdb, pandas as pd, numpy as np
c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='../../data/_ducktmp/static_mask'")
F = c.execute("SELECT *, bit_count(mmask & 63::SMALLINT) h1, bit_count((mmask >> 6) & 63::SMALLINT) h2 FROM 'feat.parquet'").df()
T = c.execute("""SELECT sx, sy, sum(t1) t1, sum(t2) FILTER (satellite='SNPP') t2v, sum(t2) FILTER (satellite<>'SNPP') t2m, sum(t3) t3,
   sum(tdays) tdays, bit_count(bit_or(tmask)) tmon, sum(tN) tN FROM 'tn0.parquet' GROUP BY 1,2""").df().fillna(0)
# R3: eruptions in the sample years whose lava FIRMS labels type 0 (not in its static-volcano list): name, year, lat0, lat1, lon0, lon1
ERUPTIONS = [('Holuhraun', 2015, 64.80, 64.95, -17.10, -16.55), ('Fagradalsfjall', 2021, 63.86, 63.92, -22.32, -22.20),
             ('La Palma (Cumbre Vieja)', 2021, 28.55, 28.70, -17.98, -17.80)]
def eruption_cells():
    q = ' UNION ALL '.join(f"SELECT sx, sy FROM 'cells/*.parquet' WHERE yr={y} AND days0q>=2 AND sy BETWEEN {int((a+90)*100)} AND {int((b+90)*100)} AND sx BETWEEN {int((e+180)*100)} AND {int((f+180)*100)}"
                           for _, y, a, b, e, f in ERUPTIONS)
    d = c.execute(f"SELECT DISTINCT * FROM ({q})").df(); d['reason'] = 'volcano'; return d
PRI = {'volcano': 0, 'offshore': 1, 'type_flag_viirs': 2, 'type_flag_modis': 3, 'persistence': 4}
def build(D=16, M=9, Y=2, tmin=3, mflag=6, buf=1, persist=True, nsmin=None, M2=4, Y2=1, spread=0, eruptions=False):
    g = T.copy(); tot = g.t1 + g.t2v + g.t2m + g.t3
    volc = g.t1 >= np.maximum(g.t2v + g.t2m, g.t3)
    g['reason'] = np.where(volc, 'volcano', np.where(g.t3 > g.t2v + g.t2m, 'offshore', np.where(g.t2v >= g.t2m, 'type_flag_viirs', 'type_flag_modis')))
    g = g[(tot >= tmin) & (volc | (g.tmon >= mflag))][['sx', 'sy', 'reason']]
    parts = [g]
    if persist:
        p = F[(F.days0q >= D) & (F.nmon >= M)].groupby(['satellite', 'sx', 'sy']).yr.nunique().reset_index()
        p = p[p.yr >= Y][['sx', 'sy']].drop_duplicates(); p['reason'] = 'persistence'; parts.append(p)
        if nsmin is not None:  # R2b: persistent and night-dominated (flares/industry are seen mostly at night), not strictly all-year
            q = F[(F.days0q >= D) & (F.nmon >= M2) & (F.nN >= nsmin * (F.nN + F.nD)) & (F.h1 >= spread) & (F.h2 >= spread)].groupby(['satellite', 'sx', 'sy']).yr.nunique().reset_index()
            q = q[q.yr >= Y2][['sx', 'sy']].drop_duplicates(); q['reason'] = 'persistence'; parts.append(q)
    if eruptions: parts.append(eruption_cells())
    m = pd.concat(parts)
    off = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)] if buf else [(0, 0)]
    m = pd.concat([m.assign(sx=m.sx + dx, sy=m.sy + dy, core=(dx == 0 and dy == 0)) for dx, dy in off])
    m['p'] = m.reason.map(PRI) - 10 * m.core
    m = m.sort_values('p').drop_duplicates(['sx', 'sy'])
    m['core'] = m.p < 0
    return m[['sx', 'sy', 'reason', 'core']].astype({'sx': 'int32', 'sy': 'int32'}).reset_index(drop=True)
def removal(m):
    c.register('mk', m[['sx', 'sy']])
    return c.execute("""SELECT satellite, sum(nD) nD, sum(nN) nN, sum(fD) fD, sum(fN) fN,
        sum(nD+nN) FILTER (nmon<=6 AND days0q>=16) n_seas_pers,
        sum(nD+nN) FILTER (sy BETWEEN 8400 AND 9400 AND sx BETWEEN 27500 AND 30000) n_indo
        FROM 'cells/*.parquet' s SEMI JOIN mk ON s.sx=mk.sx AND s.sy=mk.sy GROUP BY 1 ORDER BY 1""").df()
REF = None
def table(configs):
    tot = c.execute("""SELECT satellite, sum(nD) nD, sum(nN) nN, sum(nD+nN) FILTER (nmon<=6 AND days0q>=16) n_seas_pers,
        sum(nD+nN) FILTER (sy BETWEEN 8400 AND 9400 AND sx BETWEEN 27500 AND 30000) n_indo FROM 'cells/*.parquet' GROUP BY 1""").df().set_index('satellite')
    rows = []
    for kw in configs:
        m = build(**kw); r = removal(m).set_index('satellite'); row = dict(kw, cells=len(m), core=int(m.core.sum()))
        for s in ['Aqua', 'Terra', 'SNPP']:
            row[f'{s}_D%'] = round(100 * r.loc[s, 'nD'] / tot.loc[s, 'nD'], 2); row[f'{s}_N%'] = round(100 * r.loc[s, 'nN'] / tot.loc[s, 'nN'], 2)
        row['SNPP_removed_night_share'] = round(r.loc['SNPP', 'nN'] / (r.loc['SNPP', 'nN'] + r.loc['SNPP', 'nD']), 2)
        row['SNPP_seasonal_persistent_removed%'] = round(100 * r.loc['SNPP', 'n_seas_pers'] / tot.loc['SNPP', 'n_seas_pers'], 1)
        row['SNPP_Indonesia_removed%'] = round(100 * r.loc['SNPP', 'n_indo'] / tot.loc['SNPP', 'n_indo'], 2)
        row['Aqua_Indonesia_removed%'] = round(100 * r.loc['Aqua', 'n_indo'] / tot.loc['Aqua', 'n_indo'], 2)
        rows.append(row)
    return pd.DataFrame(rows)
