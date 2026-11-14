import duckdb, numpy as np, pandas as pd
W='work/calib_ratio'
c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='data/_ducktmp/calib_ratio'")
P=f"read_parquet('{W}/pair_*.parquet')"
CAL="(year*12+month) BETWEEN 2012*12+2 AND 2017*12+12"
mets={'n_sum':('a_n','s_n'),'frp_sum':('a_frp','s_frp'),'n_best':('a_nb','s_nb'),'frp_best':('a_fb','s_fb'),'nsub_best':('a_sb','s_sb'),'days':('a_d','s_d'),'active_cells':('(a_n>0)::INT','(s_n>0)::INT')}
sel=", ".join(f"sum({a}) a_{k}, sum({s}) s_{k}" for k,(a,s) in mets.items())
ry=c.execute(f"SELECT region,daynight,year,{sel} FROM {P} WHERE {CAL} AND region<>'OTHR' GROUP BY ALL").df()
# latitude band 10deg
lb=c.execute(f"SELECT daynight, floor((iy*0.25-90)/10)*10 lat10, {sel} FROM {P} WHERE {CAL} GROUP BY ALL").df()
# cell-month stats
cs=", ".join(f"corr(ln(1+{a}),ln(1+{s})) FILTER (WHERE true) r_{k}, median(CASE WHEN {a}>0 AND {s}>0 THEN abs(ln(({a})::DOUBLE/({s}))) END) mad_{k}, avg((({a})>0)::INT) FILTER (WHERE {s}>0) pa_{k}" for k,(a,s) in mets.items() if k!='active_cells')
cm=c.execute(f"SELECT daynight,{cs} FROM {P} WHERE {CAL} GROUP BY ALL").df()
rows=[]
for dn in 'DN':
  for k in mets:
    d=ry[ry.daynight==dn].copy(); d['r']=d[f'a_{k}']/d[f's_{k}']
    tot=d.groupby('region')[[f'a_{k}']].sum()
    big=tot[tot[f'a_{k}']>0].index
    cv=d[d.region.isin(big)].groupby('region').r.agg(lambda x: x.std()/x.mean())
    # weight by Aqua magnitude of n_sum to ignore tiny regions
    regr=d.groupby('region')[[f'a_{k}',f's_{k}']].sum(); regr=regr[f'a_{k}']/regr[f's_{k}']
    l=lb[lb.daynight==dn]; l=l[l['a_n_sum']>=2000]; lr=l[f'a_{k}']/l[f's_{k}']
    g=d[f'a_{k}'].sum()/d[f's_{k}'].sum()
    row=dict(metric=k,dn=dn,global_ratio=g,cv_year_median=cv.median(),cv_year_max=cv.max(),
             region_ratio_spread=(regr/g).max()/(regr/g).min(), region_ratio_cv=regr.std()/regr.mean(),
             lat_band_spread=lr.max()/lr.min())
    if k!='active_cells':
      m=cm[cm.daynight==dn].iloc[0]; row.update(cell_r_log=m[f'r_{k}'],cell_med_abs_logratio=m[f'mad_{k}'],P_aqua_pos_given_snpp_pos=m[f'pa_{k}'])
    rows.append(row)
R=pd.DataFrame(rows).round(3)
R.to_csv('rezultate/calib_ratio/partA_metric_stability.csv',index=False)
print(R.to_string())
for dn in 'DN':
  l=lb[(lb.daynight==dn)&(lb.a_n_sum>=2000)].sort_values('lat10')
  print(dn, 'lat-band ratios'); print(pd.DataFrame({'lat10':l.lat10,'n':(l.a_n_sum/l.s_n_sum).round(3),'frp':(l.a_frp_sum/l.s_frp_sum).round(3),'nb':(l.a_n_best/l.s_n_best).round(3),'days':(l.a_days/l.s_days).round(3),'cells':(l.a_active_cells/l.s_active_cells).round(3)}).to_string(index=False))
ry.to_parquet(f'{W}/partA_regyear.parquet')
