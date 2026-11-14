import sys, time; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model as am
T0=time.time(); V=sys.argv[1]; BO=['BONA','BOAS']
cols=['ix','iy','year','month','daynight','a_n','a_frp','s_n','s_frp','s_nb','s_fb']
cal=load(*CAL,extra=', s_nb, s_fb')[cols]; tst=load(*TEST,extra=', s_nb, s_fb')[cols]
orig=am._keys
def keys_split(d):
    d=orig(d); lat=(d.iy+0.5)*0.25-90; m=d.region.isin(BO)
    d.loc[m,'region']=d.loc[m,'region']+np.where(lat[m]>=60,'_hi','_lo'); return d
if V=='lat': am._keys=keys_split
def swap(d):  # variant b: use n_best (and frp_best) as VIIRS input in BO regions
    d=d.copy(); m=pd.Series(ec.region_of(d.ix.values,d.iy.values)).isin(BO).values
    if V in ('nbest','nbest_lat'): d.loc[m,'s_n']=d.loc[m,'s_nb']
    return d
if V=='nbest_lat': am._keys=keys_split
def P(fit,t):
    F=am.fit_factors(swap(fit)); tt=swap(t); tt=tt[tt.s_n>0]
    p=am.predict(tt[['ix','iy','year','month','daynight','s_n','s_frp']].rename(columns={'s_n':'n_sum','s_frp':'frp_sum'}),F,interval=False)
    p['s_n']=t.loc[tt.index,'s_n'].values; p['s_frp']=tt.s_frp.values; p['fpp']=np.where(tt.s_n>0,tt.s_frp/np.maximum(t.loc[tt.index,'s_n'],1),0)
    p['a_n']=tt.a_n.values; p['a_frp']=tt.a_frp.values; return p
MB=[0,10,100,1000,np.inf]
def binm(p,var):
    b=np.clip(np.digitize(p.s_n,MB)-1,0,3); return b
p=P(cal,tst)
if V=='act':  # activity-dependent multiplier for BO regions, learned from LOYO on cal only
    R=[]
    for y in CAL_YEARS:
        q=P(cal[cal.year!=y],cal[cal.year==y]); q['region']=ec.region_of(q.ix.values,q.iy.values); R.append(q[q.region.isin(BO)])
    R=pd.concat(R); Mt={}
    for var in ('n','frp'):
        for dn in 'DN':
            r=R[R.daynight==dn]; b=binm(r,var); tot=r[f'a_{var}'].sum()/r[f'pred_{var}'].sum()
            Mt[(var,dn)]=np.array([(r[f'a_{var}'][b==i].sum()/r[f'pred_{var}'][b==i].sum())/tot if (b==i).sum()>50 else 1 for i in range(4)])
            print('mult',var,dn,Mt[(var,dn)].round(3),'n per bin',np.bincount(b,minlength=4))
    pd.DataFrame([dict(var=k[0],daynight=k[1],**{f'bin{i}':v[i] for i in range(4)}) for k,v in Mt.items()]).to_csv('work/calib_ratio/act_mult.csv',index=False)
    reg=ec.region_of(p.ix.values,p.iy.values)
    for (var,dn),m in Mt.items():
        sel=(p.daynight==dn).values&np.isin(reg,BO); b=binm(p[sel],var); p.loc[sel,f'pred_{var}']*=m[b]
print('built',round(time.time()-T0,1),flush=True)
# regional bias on test incl. Aqua in SNPP-zero cells
tst['region']=ec.region_of(tst.ix.values,tst.iy.values).astype(str); p['region']=ec.region_of(p.ix.values,p.iy.values).astype(str)
ok=lambda d: d[~((d.year==2020)&d.month.isin([8,9]))]
O=ok(tst).groupby(['region','daynight'],observed=True)[['a_n','a_frp']].sum(); Pp=ok(p).groupby(['region','daynight'])[['pred_n','pred_frp']].sum()
J=O.join(Pp).fillna(0); J['bias_n']=J.pred_n/J.a_n-1; J['bias_frp']=J.pred_frp/J.a_frp-1
J=J.reset_index(); J=J[J.region!='OTHR']; J['variant']=V; J[['variant','region','daynight','bias_n','bias_frp']].to_csv(f'work/calib_ratio/hilat_{V}.csv',index=False)
for dn in 'DN':
    j=J[J.daynight==dn]; bo=j[j.region.isin(BO)]; ot=j[~j.region.isin(BO)]
    print(V,dn,'BONA n %.3f frp %.3f | BOAS n %.3f frp %.3f | others med|bias| n %.3f frp %.3f'%(*bo.set_index('region').loc['BONA',['bias_n','bias_frp']],*bo.set_index('region').loc['BOAS',['bias_n','bias_frp']],ot.bias_n.abs().median(),ot.bias_frp.abs().median()))
# region-month nmae for BO
rm=ok(p).groupby(['region','daynight','year','month'])[['pred_n','pred_frp']].sum().join(ok(tst).groupby(['region','daynight','year','month'],observed=True)[['a_n','a_frp']].sum(),how='outer').fillna(0).reset_index()
for r in BO:
    for dn in 'DN':
        g=rm[(rm.region==r)&(rm.daynight==dn)]; print(r,dn,'nmae n %.3f frp %.3f'%((g.pred_n-g.a_n).abs().sum()/g.a_n.sum(),(g.pred_frp-g.a_frp).abs().sum()/g.a_frp.sum()))
if len(sys.argv)>2: print(ec.evaluate(p[ec.KEYS+['pred_n','pred_frp']],sys.argv[2],notes=f'calib_ratio v2 variant {V}').drop(columns=['notes','time']).to_string())
print('t',round(time.time()-T0,1))
