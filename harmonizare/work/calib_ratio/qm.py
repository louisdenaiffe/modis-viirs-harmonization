import sys; sys.path.insert(0,'work/calib_ratio'); from lib import *
fit=load(*CAL); tgt=load(*TEST); tgt=tgt[tgt.s_n>0]
K=['region','daynight','year','month']
def rm(d): return d.groupby(K,observed=True)[['a_n','s_n','a_frp','s_frp']].sum().reset_index()
F=rm(fit); Tm=rm(tgt)
for var in ('n','frp'):
    a,s=VARS[var]; Tm[f'r_{var}']=np.nan
    for (r,dn),g in F.groupby(['region','daynight'],observed=True):
        xs=np.sort(g[s].values); ys=np.sort(g[a].values); m=(Tm.region==r)&(Tm.daynight==dn)
        if len(xs)<12 or xs[-1]<=0: k=g[a].sum()/max(g[s].sum(),1e-9); Tm.loc[m,f'r_{var}']=k; continue
        v=Tm.loc[m,s].values; q=np.interp(v,xs,ys)
        lo=v<xs[0]; hi=v>xs[-1]; q[lo]=v[lo]*ys[0]/max(xs[0],1e-9) if xs[0]>0 else 0; q[hi]=v[hi]*ys[-1]/xs[-1]
        Tm.loc[m,f'r_{var}']=q/np.maximum(v,1e-9)
t=tgt.merge(Tm[K+['r_n','r_frp']],on=K,how='left')
p=to_pred(t,t.r_n.values,t.r_frp.values)
print(ec.evaluate(p,'CR_B4_qm_regionmonth',notes='quantile mapping of region-month totals per region x dn (cal 2012-17), cells scaled proportionally').drop(columns=['notes','time']).to_string())
