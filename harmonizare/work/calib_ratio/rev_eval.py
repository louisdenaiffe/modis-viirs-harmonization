import sys, time; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model_reverse as amr
T0=time.time(); t=load(*TEST); t=t[~((t.year==2020)&t.month.isin([8,9]))]
x=t[t.a_n>0]; p=amr.predict(x[['ix','iy','year','month','daynight','a_n','a_frp']].rename(columns={'a_n':'n_sum','a_frp':'frp_sum'}))
T=t[['ix','iy','year','month','daynight','region','s_n','s_frp']].copy(); T['daynight']=T.daynight.astype(str); T['region']=T.region.astype(str)
T=T.merge(p,on=['ix','iy','year','month','daynight'],how='left').fillna({'pred_n':0,'pred_frp':0,'lo_n':0,'hi_n':0,'lo_frp':0,'hi_frp':0})
T.rename(columns={'s_n':'obs_n','s_frp':'obs_frp'}).to_parquet('work/calib_ratio/rev_test_cells.parquet')
# cell-level interval coverage (cells with pred>0)
for var in ('n','frp'):
    for dn in 'DN':
        d=T[(T.daynight==dn)&(T[f'pred_{var}']>0)]; o=d[f's_{var}']
        print('cell coverage',var,dn,round(((o>=d[f'lo_{var}'])&(o<=d[f'hi_{var}'])).mean(),3),'| share of VIIRS total in cells with pred=0:',round(T[(T.daynight==dn)&(T[f'pred_{var}']==0)][f's_{var}'].sum()/T[T.daynight==dn][f's_{var}'].sum(),3))
rm=T.groupby(['region','daynight','year','month'])[['s_n','s_frp','pred_n','pred_frp']].sum().reset_index()
g=rm.groupby(['daynight','year','month'])[['s_n','s_frp','pred_n','pred_frp']].sum().reset_index(); g['region']='GLOBAL'
rows=[]
for (r,dn),q in pd.concat([rm[rm.region!='OTHR'],g]).groupby(['region','daynight']):
    row=dict(region=r,daynight=dn,n_months=len(q))
    for var in ('n','frp'):
        o=q[f's_{var}'].values; pr=q[f'pred_{var}'].values
        row.update({f'{var}_obs_total':o.sum(),f'{var}_bias':pr.sum()/o.sum()-1,f'{var}_mae_rel':np.abs(pr-o).sum()/o.sum(),f'{var}_rmse_rel':np.sqrt(((pr-o)**2).mean())/o.mean(),
                    f'{var}_r':np.corrcoef(o,pr)[0,1]})
    rows.append(row)
E=pd.DataFrame(rows); E.round(4).to_csv('rezultate/calib_ratio/reverse_eval_regions.csv',index=False)
pd.set_option('display.width',250); print(E.drop(columns=['n_obs_total','frp_obs_total']).round(3).to_string(index=False))
for dn in 'DN':
    e=E[(E.daynight==dn)&(E.region!='GLOBAL')]
    print(dn,'regional median: |bias| n %.3f frp %.3f | MAE n %.3f frp %.3f | RMSE n %.3f frp %.3f | worst |bias| n %.3f frp %.3f'%(e.n_bias.abs().median(),e.frp_bias.abs().median(),e.n_mae_rel.median(),e.frp_mae_rel.median(),e.n_rmse_rel.median(),e.frp_rmse_rel.median(),e.n_bias.abs().max(),e.frp_bias.abs().max()))
print('t',round(time.time()-T0,1))
