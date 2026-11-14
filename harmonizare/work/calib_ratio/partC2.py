import sys; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model as am
R=pd.read_parquet('work/calib_ratio/loyo_resid.parquet')
RB={'n':[0,100,1000,10000,np.inf],'frp':[0,1e3,1e4,1e5,np.inf]}
def tab(df,bins,level):
    rows=[]
    for var in ('n','frp'):
        for dn in 'DN':
            d=df[(df.daynight==dn)&(df[f'pred_{var}']>0)]; b=np.clip(np.digitize(d[f'pred_{var}'],bins[var])-1,0,len(bins[var])-2); r=d[f'obs_{var}']/d[f'pred_{var}']
            for i in range(len(bins[var])-1):
                x=r[b==i]
                if len(x)<30: continue
                rows.append(dict(level=level,var=var,daynight=dn,bin=i,bin_lo=bins[var][i],bin_hi=bins[var][i+1],lo=x.quantile(.1),hi=x.quantile(.9),median=x.median(),n_obs=len(x)))
    return pd.DataFrame(rows)
Ic=tab(R,am.BINS,'interval_cell')
Rm=R.groupby(['region','daynight','year','month'])[['obs_n','pred_n','obs_frp','pred_frp']].sum().reset_index()
# add Aqua in cells where SNPP=0 (pred 0) to region-month obs
cal=load(*CAL); z=cal[cal.s_n==0].groupby(['region','daynight','year','month'],observed=True)[['a_n','a_frp']].sum().reset_index(); z['region']=z.region.astype(str); z['daynight']=z.daynight.astype(str)
Rm=Rm.merge(z,how='left').fillna(0); Rm['obs_n']+=Rm.a_n; Rm['obs_frp']+=Rm.a_frp; Rm=Rm[Rm.region!='OTHR']
Ir=tab(Rm,RB,'interval_regionmonth')
I=pd.concat([Ic,Ir]); print(I.round(3).to_string())
F=pd.read_parquet('work/calib_ratio/factors_noint.parquet'); F=pd.concat([F,I],ignore_index=True)
F.to_parquet('rezultate/calib_ratio/factors.parquet'); F.to_csv('rezultate/calib_ratio/factors.csv',index=False)
# coverage on test
tgt=load(*TEST); s=tgt[tgt.s_n>0]
p=am.predict(s[['ix','iy','year','month','daynight','s_n','s_frp']].rename(columns={'s_n':'n_sum','s_frp':'frp_sum'}))
p['obs_n']=s.a_n.values; p['obs_frp']=s.a_frp.values; p['region']=s.region.astype(str).values
p=p[~((p.year==2020)&p.month.isin([8,9]))]
for var in ('n','frp'):
    for dn in 'DN':
        d=p[(p.daynight==dn)&(p[f'pred_{var}']>0)]; print('cell coverage',var,dn,round(((d[f'obs_{var}']>=d[f'lo_{var}'])&(d[f'obs_{var}']<=d[f'hi_{var}'])).mean(),3),'below',round((d[f'obs_{var}']<d[f'lo_{var}']).mean(),3),'above',round((d[f'obs_{var}']>d[f'hi_{var}']).mean(),3))
Tm=p.groupby(['region','daynight','year','month'])[['obs_n','pred_n','obs_frp','pred_frp']].sum().reset_index()
z=tgt[tgt.s_n==0].groupby(['region','daynight','year','month'],observed=True)[['a_n','a_frp']].sum().reset_index(); z['region']=z.region.astype(str); z['daynight']=z.daynight.astype(str)
Tm=Tm.merge(z,how='left').fillna(0); Tm['obs_n']+=Tm.a_n; Tm['obs_frp']+=Tm.a_frp; Tm=Tm[Tm.region!='OTHR']
for var in ('n','frp'):
    for dn in 'DN':
        d=Tm[(Tm.daynight==dn)&(Tm[f'pred_{var}']>0)].copy(); q=Ir[(Ir['var']==var)&(Ir.daynight==dn)].set_index('bin')
        b=np.clip(np.digitize(d[f'pred_{var}'],RB[var])-1,0,len(RB[var])-2); lo=q.lo.reindex(range(len(RB[var])-1)).ffill().bfill().values[b]; hi=q.hi.reindex(range(len(RB[var])-1)).ffill().bfill().values[b]
        r=d[f'obs_{var}']/d[f'pred_{var}']; print('regmonth coverage',var,dn,round(((r>=lo)&(r<=hi)).mean(),3),'n',len(d))
