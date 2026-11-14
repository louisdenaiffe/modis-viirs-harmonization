import sys, time; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model as am
T0=time.time(); cal=load(*CAL); cols=['ix','iy','year','month','daynight','a_n','a_frp','s_n','s_frp']; R=[]
for y in CAL_YEARS:
    F=am.fit_factors(cal.loc[cal.year!=y,cols]); t=cal[(cal.year==y)&(cal.s_n>0)]
    p=am.predict(t[['ix','iy','year','month','daynight','s_n','s_frp']].rename(columns={'s_n':'n_sum','s_frp':'frp_sum'}),F,interval=False)
    R.append(pd.DataFrame({'daynight':t.daynight.astype(str).values,'region':t.region.astype(str).values,'year':y,'month':t.month.values,
        'obs_n':t.a_n.values,'pred_n':p.pred_n.values,'obs_frp':t.a_frp.values,'pred_frp':p.pred_frp.values})); print(y,round(time.time()-T0,1),flush=True)
R=pd.concat(R); R.to_parquet('work/calib_ratio/loyo_resid.parquet')
