import sys, time; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model_reverse as amr
T0=time.time()
N0={('n','D'):(1e5,300.),('n','N'):(1e4,300.),('frp','D'):(1e6,1e5),('frp','N'):(1e6,1e4)}
def prep(d): return d.rename(columns={'s_n':'t_n','s_frp':'t_frp','a_n':'i_n','a_frp':'i_frp'})[['ix','iy','year','month','daynight','t_n','t_frp','i_n','i_frp']]
cal=prep(load(*CAL)); R=[]
for y in CAL_YEARS:
    F=amr.fit_factors(cal[cal.year!=y],N0); t=cal[(cal.year==y)&(cal.i_n>0)]
    p=amr.predict(t.rename(columns={'i_n':'n_sum','i_frp':'frp_sum'}),F,interval=False)
    R.append(pd.DataFrame({'daynight':t.daynight.astype(str).values,'obs_n':t.t_n.values,'pred_n':p.pred_n.values,'obs_frp':t.t_frp.values,'pred_frp':p.pred_frp.values}))
R=pd.concat(R); rows=[]
for var in ('n','frp'):
    for dn in 'DN':
        d=R[(R.daynight==dn)&(R[f'pred_{var}']>0)]; B=amr.BINS[var]; b=np.clip(np.digitize(d[f'pred_{var}'],B)-1,0,len(B)-2); r=d[f'obs_{var}']/d[f'pred_{var}']
        for i in range(len(B)-1):
            x=r[b==i]
            if len(x)>=30: rows.append(dict(level='interval_cell',var=var,daynight=dn,bin=i,bin_lo=B[i],bin_hi=B[i+1],lo=x.quantile(.1),hi=x.quantile(.9),median=x.median(),n_obs=len(x)))
I=pd.DataFrame(rows); print(I.round(3).to_string())
F=amr.fit_factors(cal,N0)
C=pd.DataFrame([dict(level='constants',var=v,daynight=dn,n0_season=a,n0_cell=b) for (v,dn),(a,b) in N0.items()])
F=pd.concat([F,I,C],ignore_index=True); F.to_parquet('rezultate/calib_ratio/factors_reverse.parquet')
print(F[F.level=='region_season'].groupby(['var','daynight']).k.describe().round(3).to_string()); print('t',round(time.time()-T0,1))
