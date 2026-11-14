import sys; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model as v1, apply_model_v2 as am2
t=load(2018,1,2021,12,extra=', s_nb'); t=t[(t.daynight=='D')&t.region.isin(['BOAS','BONA'])]
s=t[t.s_n>0]; df=s[['ix','iy','year','month','daynight','s_n','s_frp','s_nb']].rename(columns={'s_n':'n_sum','s_frp':'frp_sum','s_nb':'n_best'})
p1=v1.predict(df,interval=False); p2=am2.predict(df)
s=s.assign(v1=p1.pred_n.values,v2=p2.pred_n.values,lo=p2.lo_n.values,hi=p2.hi_n.values,yak=((s.ix>=(105+180)*4)&(s.ix<(150+180)*4)&(s.iy>=(58+90)*4)&(s.iy<(72+90)*4)).values)
g=s.groupby(['region','year','month'],observed=True)[['a_n','v1','v2']].sum().reset_index(); g=g[g.a_n>3000]
g['v1_err%']=100*(g.v1/g.a_n-1); g['v2_err%']=100*(g.v2/g.a_n-1); print(g.round(0).to_string(index=False))
o=t[((t.ix>=(105+180)*4)&(t.ix<(150+180)*4)&(t.iy>=(58+90)*4)&(t.iy<(72+90)*4))&(t.year==2021)&t.month.isin([7,8])].a_n.sum()
y=s[s.yak&(s.year==2021)&s.month.isin([7,8])]; print('Yakutia box Jul-Aug 2021 Aqua',o,'v1',round(y.v1.sum()),'v2',round(y.v2.sum()))
