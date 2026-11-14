# LOYO within 2012-02..2017-12: choose (n0_season, n0_cell) per var x dn from 3x3 candidates; loss = sum |V - k*A| over held-out cell-months
import sys, time, itertools; sys.path.insert(0,'work/calib_ratio'); from lib import *
T0=time.time(); var=sys.argv[1]
d=load(*CAL); d['season']=((d.month%12)//3).astype('int8')
a,s={'n':('s_n','a_n'),'frp':('s_frp','a_frp')}[var]   # target VIIRS, input Aqua
CS={'n':[100,1000,10000],'frp':[1e3,1e4,1e5]}[var]; CC={'n':[3,30,300],'frp':[100,1000,10000]}[var]
if len(sys.argv)>2: CS=[c*10 for c in CS]; CC=[c*10 for c in CC]
res=[]
for dn in 'DN':
    x=d[d.daynight==dn]; L={k:0.0 for k in itertools.product(CS,CC)}; L['region_only']=0.0
    for y in CAL_YEARS:
        f=x[x.year!=y]; t=x[x.year==y]
        st=lambda keys: f.groupby(keys,observed=True)[[a,s]].sum().rename(columns={a:'A',s:'S'}).reset_index()
        r=st(['region']); r['kr']=r.A/r.S.clip(lower=1e-9); kg=f[a].sum()/f[s].sum(); r.loc[r.S<=0,'kr']=kg
        m=t[['region','season','b2','cell',a,s]].merge(r[['region','kr']],how='left')
        m=m.merge(st(['region','season']).rename(columns={'A':'As','S':'Ss'}),how='left').merge(st(['region','b2']).rename(columns={'A':'Ab','S':'Sb'}),how='left').merge(st(['region','cell']).rename(columns={'A':'Ac','S':'Sc'}),how='left')
        m=m.fillna({'kr':kg}); nc_=['As','Ss','Ab','Sb','Ac','Sc']; m[nc_]=m[nc_].fillna(0); V=m[a].values; I=m[s].values; kr=m.kr.values
        for ns,nc in itertools.product(CS,CC):
            krs=(m.As.values+ns*kr)/(m.Ss.values+ns); kb=(m.Ab.values+nc*kr)/(m.Sb.values+nc); kc=(m.Ac.values+nc*kb)/(m.Sc.values+nc)
            L[(ns,nc)]+=np.abs(V-krs*kc/kr*I).sum()
        L['region_only']+=np.abs(V-kr*I).sum()
    for k,v in L.items(): res.append(dict(var=var,daynight=dn,n0_season=k[0] if k!='region_only' else np.nan,n0_cell=k[1] if k!='region_only' else np.nan,loyo_abs_err=v,rel_to_region_only=v/L['region_only']))
    print(dn,round(time.time()-T0,1),flush=True)
R=pd.DataFrame(res); R.to_csv(f'work/calib_ratio/rev_cv_{var}{"_x10" if len(sys.argv)>2 else ""}.csv',index=False); print(R.round(4).to_string())
