import pandas as pd, numpy as np, time
T0=time.time(); T=pd.read_parquet('work/calib_ratio/rev_test_cells.parquet',columns=['ix','iy','year','month','daynight','obs_n','obs_frp','pred_n','pred_frp'])
BN={'n':[1,10,100,1000,10000,np.inf],'frp':[0,1e2,1e3,1e4,1e5,np.inf]}
LAB={'n':['1-9','10-99','100-999','1000-9999','>=10000'],'frp':['0-1e2','1e2-1e3','1e3-1e4','1e4-1e5','>=1e5']}
rows=[]
for s in (0.25,0.5,1,2,5):
    f=int(round(s/0.25)); d=T.assign(bx=(T.ix//f).astype('int32'),by=(T.iy//f).astype('int32'))
    for agg in ('monthly','annual'):
        keys=['bx','by','year']+(['month'] if agg=='monthly' else [])
        g=d.groupby(keys+['daynight'])[['obs_n','obs_frp','pred_n','pred_frp']].sum().reset_index()
        ga=g.groupby(keys)[['obs_n','obs_frp','pred_n','pred_frp']].sum().reset_index(); ga['daynight']='ALL'; g=pd.concat([g,ga])
        for dn in ('D','N','ALL'):
            for var in ('n','frp'):
                q=g[g.daynight==dn]; p=q[f'pred_{var}'].values; o=q[f'obs_{var}'].values
                b=np.digitize(p,BN[var])-1; ok=(p>0)&(b>=0)&(b<5)
                with np.errstate(divide='ignore',invalid='ignore'):
                    rel=np.clip(np.where(o>0,(p-o)/o,3.0),-3,3); ratio=np.clip(np.where(o>0,p/o,100.0),0,100)
                for i in range(5):
                    m=ok&(b==i)
                    if m.sum()<20: continue
                    r=rel[m]; rows.append(dict(agg=agg,scale_deg=s,daynight=dn,var=var,activity_bin=LAB[var][i],n_block_months=int(m.sum()),
                        median_abs_pct_err=100*np.median(np.abs(r)),rms_pct_err=100*np.sqrt((r**2).mean()),p10_ratio=np.quantile(ratio[m],.1),p90_ratio=np.quantile(ratio[m],.9),
                        share_within_20pct=(np.abs(r)<=.2).mean(),share_within_50pct=(np.abs(r)<=.5).mean()))
                # block-months the model cannot see: pred==0 but obs>0
                z=(p==0)&(o>0); rows.append(dict(agg=agg,scale_deg=s,daynight=dn,var=var,activity_bin='pred=0 (missed)',n_block_months=int(z.sum()),
                    median_abs_pct_err=100.0 if z.any() else np.nan,rms_pct_err=100.0 if z.any() else np.nan,p10_ratio=0,p90_ratio=0,share_within_20pct=0,share_within_50pct=0))
    print(s,round(time.time()-T0,1),flush=True)
A=pd.DataFrame(rows).round(3); A.to_csv('rezultate/calib_ratio/accuracy_viirs_scale.csv',index=False)
pd.set_option('display.width',250)
print(A[(A['var']=='n')&(A.agg=='monthly')&(A.daynight!='D')][['scale_deg','daynight','activity_bin','n_block_months','median_abs_pct_err','rms_pct_err','p10_ratio','p90_ratio','share_within_20pct','share_within_50pct']].to_string(index=False))
