import sys, time; sys.path.insert(0,'work/calib_ratio'); from lib import *
T0=time.time(); name=sys.argv[1]
CH={'B2':[['region'],['region','season']], 'B3':[['region'],['b2'],['cell']], 'B3h':[['region'],['latb','sect'],['b2'],['cell']]}[name]
G={'B2':{'n':[300,3000,30000],'frp':[1e3,1e4,1e5]}, 'B3':{'n':[10,100,1000],'frp':[100,1000,10000]}}[name[:2]]
d=load(*CAL); rows=[]
for var in ('n','frp'):
    a,s=VARS[var]; folds=[]
    for y in CAL_YEARS:
        fit=d[d.year!=y]; t=d[d.year==y]
        k0,L=hier_stats(fit,t,CH,var); folds.append((k0,L,t[a].values,t[s].values,t.daynight.values=='D'))
    for nn in G[var]+[1e12]:
        e={'D':0,'N':0}
        for k0,L,A,S,isd in folds:
            k=hier_apply(k0,L,[1e-9]+[nn]*(len(CH)-1)); err=np.abs(A-k*S); e['D']+=err[isd].sum(); e['N']+=err[~isd].sum()
        rows.append(dict(chain=name,var=var,n0=nn,loyo_abs_err_D=e['D'],loyo_abs_err_N=e['N']))
    print(var, round(time.time()-T0,1), flush=True)
R=pd.DataFrame(rows); print(R.to_string()); R.to_csv(f'rezultate/calib_ratio/cv_{name}.csv',index=False)
