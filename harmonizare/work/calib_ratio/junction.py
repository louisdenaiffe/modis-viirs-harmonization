import pandas as pd, numpy as np
d=pd.read_csv('rezultate/final/region_month.csv'); print(d.daynight.unique(), sorted(d.region.unique()))
d['t']=d.year*12+d.month-1; rows=[]
def stat(x,t0,var):
    b=x[(x.t>=t0-12)&(x.t<t0)][var].sum(); a=x[(x.t>=t0)&(x.t<t0+12)][var].sum()
    return np.log(a/b) if a>0 and b>0 else np.nan
for (r,dn),x in d[d.daynight.isin(['D','N'])&(d.region!='OTHR')].groupby(['region','daynight']):
    for var in ('n_eq','frp_eq'):
        for name,t0,mon in (('2002-07',2002*12+6,7),('2022-01',2022*12,1)):
            j=stat(x,t0,var)
            pl=np.array([stat(x,y*12+mon-1,var) for y in range(2003 if mon==7 else 2004,2022 if mon==7 else 2022) if (y*12+mon-1)+12<=2022*12 and (y*12+mon-1)-12>=2002*12+6])
            pl=pl[np.isfinite(pl)]
            # exclude the 2020 Aug-Sep swap? placebo windows use the final record as is
            rows.append(dict(region=r,dn=dn,var=var[:-3],junction=name,change_pct=100*(np.exp(j)-1),pl_min=100*(np.exp(pl.min())-1),pl_max=100*(np.exp(pl.max())-1),
                 pl_sd_log=pl.std(),z=(j-pl.mean())/pl.std(),pctile=(pl<j).mean(),n_pl=len(pl),outside=(j<pl.min())|(j>pl.max())))
R=pd.DataFrame(rows).round(3); R.to_csv('rezultate/calib_ratio/junction_audit.csv',index=False)
print(R[R.outside|(R.z.abs()>2)].to_string())
print(R.groupby(['junction','dn','var']).agg(n=('outside','size'),outside=('outside','sum'),absz_med=('z',lambda s:s.abs().median())).to_string())
