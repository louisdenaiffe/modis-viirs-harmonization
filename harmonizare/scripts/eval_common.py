"""eval_common.py — the ONE shared evaluation protocol for every harmonization candidate.
Target  : Aqua MODIS monthly totals per 0.25 deg cell and day/night (n_sum = fire pixels, frp_sum = MW),
          type 0, confidence not low  ->  "Aqua-equivalent" units.
Input   : Suomi-NPP VIIRS (same filters).  Calibrate on 2012-02..2017-12, test on 2018-01..2021-12
          (Aug+Sep 2020 excluded: Aqua outage). 2022+ is NOT used: Aqua's orbit drifts.
Usage   : import sys; sys.path.insert(0, 'harmonizare/scripts'); import eval_common as ec
          ec.evaluate(pred_df, 'my_model_name', notes='...')
          pred_df columns: ix, iy, year, month, daynight, pred_n and/or pred_frp  (test period rows; missing rows count as 0)"""
import duckdb, numpy as np, pandas as pd, os, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONTHLY = f"{ROOT}/data/grid/monthly_025/*.parquet"
CAL = (2012 * 12 + 2, 2017 * 12 + 12); TEST = (2018 * 12 + 1, 2021 * 12 + 12)
EXCLUDE = [(2020, 8), (2020, 9)]
KEYS = ['ix', 'iy', 'year', 'month', 'daynight']
REGIONS = [  # name, lat_min, lat_max, lon_min, lon_max  (first match wins; coarse GFED-like boxes)
    ('BONA', 50, 90, -170, -50), ('TENA', 30, 50, -130, -50), ('CEAM', 13, 30, -120, -58), ('NHSA', 0, 13, -93, -48),
    ('SHSA', -60, 0, -93, -30), ('EURO', 35, 75, -25, 40), ('MIDE', 23, 35, -18, 62), ('MIDE', 12, 23, 35, 62),
    ('NHAF', 0, 23, -20, 52), ('SHAF', -40, 0, 5, 52), ('BOAS', 50, 90, 40, 180), ('CEAS', 30, 50, 40, 150),
    ('SEAS', 5, 30, 62, 125), ('EQAS', -11, 5, 90, 160), ('AUST', -50, -11, 110, 180)]

def region_of(ix, iy):
    lon = (np.asarray(ix) + 0.5) * 0.25 - 180; lat = (np.asarray(iy) + 0.5) * 0.25 - 90
    out = np.full(lon.shape, 'OTHR', dtype=object)
    for name, la0, la1, lo0, lo1 in reversed(REGIONS):
        out[(lat >= la0) & (lat < la1) & (lon >= lo0) & (lon < lo1)] = name
    return out

def con():
    c = duckdb.connect(); c.execute("SET memory_limit='700MB'; SET threads=2; SET preserve_insertion_order=false")
    os.makedirs(f'{ROOT}/data/_ducktmp', exist_ok=True); c.execute(f"SET temp_directory='{ROOT}/data/_ducktmp'")
    return c

def ym_filter(period):
    return f"(year * 12 + month) BETWEEN {period[0]} AND {period[1]}"

def load(satellite, period, cols=('n_sum', 'frp_sum')):
    """Monthly rows of one satellite ('Aqua', 'Terra', 'SNPP') for a (start, end) period as pandas."""
    return con().execute(f"SELECT {', '.join(KEYS)}, {', '.join(cols)} FROM read_parquet('{MONTHLY}') "
                         f"WHERE satellite = '{satellite}' AND {ym_filter(period)}").df()

def _agg(df, by, cols):
    return df.groupby(by, observed=True)[cols].sum().reset_index()

def evaluate(pred, label, notes='', write=True):
    obs = load('Aqua', TEST).rename(columns={'n_sum': 'obs_n', 'frp_sum': 'obs_frp'})
    pred = pred.copy()
    pred = pred[(pred.year * 12 + pred.month).between(*TEST)]
    df = obs.merge(pred, on=KEYS, how='outer').fillna(0)
    for y, m in EXCLUDE: df = df[~((df.year == y) & (df.month == m))]
    df['region'] = region_of(df.ix.values, df.iy.values)
    # Aqua climatology 2003-2017 per region x calendar month x daynight -> tercile thresholds
    c = con(); cells = pd.DataFrame({'ix': np.repeat(np.arange(1440), 720), 'iy': np.tile(np.arange(720), 1440)})
    cells['region'] = region_of(cells.ix.values, cells.iy.values); c.register('cells', cells)
    clim = c.execute(f"""SELECT region, daynight, year, month, sum(n_sum) n, sum(frp_sum) frp FROM read_parquet('{MONTHLY}') m
        JOIN cells USING (ix, iy) WHERE satellite = 'Aqua' AND year BETWEEN 2003 AND 2017 GROUP BY ALL""").df()
    rows = []
    for var in ('n', 'frp'):
        if f'pred_{var}' not in df: continue
        for dn in ('D', 'N'):
            d = df[df.daynight == dn]; o, p = d[f'obs_{var}'].values, d[f'pred_{var}'].values
            rm = _agg(d, ['region', 'year', 'month'], [f'obs_{var}', f'pred_{var}'])
            reg = []
            for r, g in rm.groupby('region'):
                so = g[f'obs_{var}'].sum()
                if r == 'OTHR' or so <= 0 or len(g) < 12: continue
                reg.append(dict(region=r, obs_total=so, bias=g[f'pred_{var}'].sum() / so - 1,
                                nmae=np.abs(g[f'pred_{var}'] - g[f'obs_{var}']).sum() / so,
                                r=np.corrcoef(g[f'obs_{var}'], g[f'pred_{var}'])[0, 1]))
            reg = pd.DataFrame(reg)
            gm = _agg(d, ['year', 'month'], [f'obs_{var}', f'pred_{var}'])
            # tercile class agreement at region-month level
            cl = clim[clim.daynight == dn].groupby(['region', 'month'])[var].quantile([1 / 3, 2 / 3]).unstack().reset_index()
            cl.columns = ['region', 'month', 't1', 't2']; t = rm.merge(cl, on=['region', 'month']); t = t[t.region != 'OTHR']
            k = lambda v: (v > t.t1).astype(int) + (v > t.t2).astype(int)
            row = dict(time=time.strftime('%H:%M'), label=label, var=var, daynight=dn,
                       cell_mae=np.abs(p - o).mean(), cell_r_log=np.corrcoef(np.log1p(o), np.log1p(np.clip(p, 0, None)))[0, 1],
                       glob_bias=p.sum() / o.sum() - 1, glob_nmae=np.abs(gm[f'pred_{var}'] - gm[f'obs_{var}']).sum() / o.sum(),
                       reg_med_abs_bias=reg.bias.abs().median(), reg_max_abs_bias=reg.bias.abs().max(),
                       reg_med_nmae=reg.nmae.median(), reg_med_r=reg.r.median(),
                       tercile_acc=(k(t[f'pred_{var}']) == k(t[f'obs_{var}'])).mean(), notes=notes)
            rows.append(row)
            if write:
                os.makedirs(f'{ROOT}/rezultate/eval', exist_ok=True)
                reg.round(4).to_csv(f'{ROOT}/rezultate/eval/{label}_{var}_{dn}_regions.csv', index=False)
    res = pd.DataFrame(rows).round(4)
    if write:
        lb = f'{ROOT}/rezultate/leaderboard.csv'
        res.to_csv(lb, mode='a', header=not os.path.exists(lb), index=False)
    return res

if __name__ == '__main__':  # baseline M0: raw VIIRS used as if it were MODIS
    v = load('SNPP', TEST).rename(columns={'n_sum': 'pred_n', 'frp_sum': 'pred_frp'})
    print(evaluate(v, 'M0_raw_viirs', notes='no correction').to_string())
    # baseline M1: one global ratio per day/night learned on the calibration period
    a, s = load('Aqua', CAL), load('SNPP', CAL)
    for dn in 'DN':
        for var, col in (('n', 'n_sum'), ('frp', 'frp_sum')):
            k = a[a.daynight == dn][col].sum() / s[s.daynight == dn][col].sum(); print('global ratio', dn, var, round(k, 4))
            v.loc[v.daynight == dn, f'pred_{var}'] *= k
    print(evaluate(v, 'M1_global_ratio', notes='one Aqua/SNPP ratio per day/night, cal 2012-2017').to_string())
