import pandas as pd, numpy as np, pyarrow.parquet as pq, pyarrow.dataset as ds, sys
sys.path.insert(0, 'scripts'); import eval_common as ec
W = 'work/calib_physics_ml'; R = 'rezultate/calib_physics_ml'
B = ['lt3', '3_6', '6_10', '10_20', '20_50', 'ge50']
CB = [f'c_{b}' for b in B]; FB = [f'f_{b}' for b in B]
REGS = sorted(set(r[0] for r in ec.REGIONS)) + ['OTHR']
def load(years, dn=None, cols=None, period=None):
    out = []
    for y in years:
        t = pq.read_table(f'{W}/joined_{y}.parquet', columns=None if cols is None else list(dict.fromkeys(['ix','iy','year','month','daynight','region'] + cols)))
        d = t.to_pandas()
        if dn: d = d[d.daynight == dn]
        out.append(d)
    d = pd.concat(out, ignore_index=True)
    d['region'] = pd.Categorical(d.region, categories=REGS)
    ym = d.year * 12 + d.month
    if period: d = d[ym.between(*period)]
    return d.reset_index(drop=True)
def cal(dn=None, cols=None): return load(range(2012, 2018), dn, cols, ec.CAL)
def test(dn=None, cols=None):
    d = load(range(2018, 2022), dn, cols, ec.TEST)
    for y, m in ec.EXCLUDE: d = d[~((d.year == y) & (d.month == m))]
    return d.reset_index(drop=True)
def quick(d, pred, obs):
    """quick metrics on a frame: cell MAE, global bias, median/max |regional bias|"""
    g = pd.DataFrame({'r': d.region.values, 'p': pred, 'o': d[obs].values}).groupby('r', observed=True).sum()
    g = g[(g.index != 'OTHR') & (g.o > 0)]; b = g.p / g.o - 1
    return dict(mae=np.abs(pred - d[obs].values).mean(), gbias=pred.sum() / d[obs].sum() - 1,
                reg_med=b.abs().median(), reg_max=b.abs().max())
def splice(d, pred, obs):
    g = pd.DataFrame({'r': d.region.values, 'p': pred, 'o': d[obs].values}).groupby('r', observed=True).sum()
    return (g.p / g.o - 1).round(3)
