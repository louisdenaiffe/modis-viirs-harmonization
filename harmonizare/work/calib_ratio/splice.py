import sys; sys.path.insert(0,'work/calib_ratio'); from lib import *
rng=np.random.default_rng(0)
A=pd.read_parquet('work/calib_ratio/regmonth_aqua_snpp.parquet'); A=A[(A.satellite=='Aqua')&(A.year.between(2003,2021))&(A.region!='OTHR')]
H=pd.read_csv('rezultate/calib_ratio/harmonized_regionmonth.csv')
K=['region','daynight','year','month']
D=A[K+['n','frp']].merge(H[K+['pred_n','pred_frp']],on=K,how='left')
D=D[~((D.year==2020)&D.month.isin([8,9]))]
rows=[]
for (r,dn),g in D.groupby(['region','daynight']):
    for var in ('n','frp'):
        t=g[g.year>=2018]; o=t[var].values; p=t[f'pred_{var}'].fillna(0).values
        if o.sum()<=0 or len(t)<24: continue
        step=p.mean()/o.mean()-1; bs=[]
        for _ in range(1000):
            i=rng.integers(0,len(o),len(o)); bs.append(p[i].mean()/max(o[i].mean(),1e-9)-1)
        real=g[var].values; spl=np.where(g.year>=2018,g[f'pred_{var}'].fillna(0),g[var]).astype(float)
        fr=real>=np.quantile(real,.9); fs=spl>=np.quantile(spl,.9); w=(g.year>=2018).values
        tp=(fr&fs&w).sum(); prec=tp/max((fs&w).sum(),1); rec=tp/max((fr&w).sum(),1)
        rows.append(dict(region=r,dn=dn,var=var,step_pct=100*step,ci_lo=100*np.quantile(bs,.05),ci_hi=100*np.quantile(bs,.95),flags_real=int((fr&w).sum()),flags_spliced=int((fs&w).sum()),precision=prec,recall=rec))
S=pd.DataFrame(rows).round(2); S.to_csv('rezultate/calib_ratio/splice_test.csv',index=False); print(S.to_string())
for var in ('n','frp'):
    for dn in 'DN':
        s=S[(S['var']==var)&(S.dn==dn)]; print(var,dn,'median|step|',s.step_pct.abs().median(),'n regions CI excl 0',((s.ci_lo>0)|(s.ci_hi<0)).sum(),'/',len(s),'pooled prec',round((s.precision*s.flags_spliced).sum()/s.flags_spliced.sum(),3),'rec',round((s.recall*s.flags_real).sum()/s.flags_real.sum(),3))
