import sys; sys.argv=[sys.argv[0],'none']; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model as am
BO=['BONA','BOAS']; orig=am._keys
def keys_split(d):
    d=orig(d); lat=(d.iy+0.5)*0.25-90; m=d.region.isin(BO); d.loc[m,'region']=d.loc[m,'region']+np.where(lat[m]>=60,'_hi','_lo'); return d
cols=['ix','iy','year','month','daynight','a_n','a_frp','s_n','s_frp','s_nb']
cal=load(*CAL,extra=', s_nb')[cols]; cal=cal[cal.daynight=='D']; cal['region']=ec.region_of(cal.ix.values,cal.iy.values).astype(str); cal=cal[cal.region.isin(BO)]
rows=[]
for V in ('base','lat','nbest','nbest_lat'):
    am._keys=keys_split if 'lat' in V else orig
    d=cal.copy()
    if 'nbest' in V: d['s_n']=d.s_nb
    for y in CAL_YEARS:
        F=am.fit_factors(d[d.year!=y]); t=d[(d.year==y)&(d.s_n>0)]
        p=am.predict(t[['ix','iy','year','month','daynight','s_n','s_frp']].rename(columns={'s_n':'n_sum','s_frp':'frp_sum'}),F,interval=False)
        t=t.assign(pred=p.pred_n.values)
        for r in BO:
            obs=d[(d.year==y)&(d.region==r)].a_n.sum(); g=t[t.region==r]
            rm=g.groupby('month').pred.sum().reindex(range(1,13),fill_value=0); om=d[(d.year==y)&(d.region==r)].groupby('month').a_n.sum().reindex(range(1,13),fill_value=0)
            rows.append(dict(V=V,region=r,year=y,bias=g.pred.sum()/obs-1,rm_nmae=(rm-om).abs().sum()/obs,cell_ae=(g.pred-g.a_n).abs().sum()/obs))
R=pd.DataFrame(rows); R.to_csv('work/calib_ratio/hilat_loyo.csv',index=False)
print(R.groupby(['region','V']).agg(med_abs_bias=('bias',lambda s:s.abs().median()),mean_bias=('bias','mean'),sd_bias=('bias','std'),rm_nmae=('rm_nmae','mean'),cell_ae=('cell_ae','mean')).round(3).to_string())
