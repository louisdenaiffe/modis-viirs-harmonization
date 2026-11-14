import pandas as pd, numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
A=pd.read_parquet('work/calib_ratio/regmonth_aqua_snpp.parquet'); A=A[(A.daynight=='D')&A.year.between(2003,2021)]
H=pd.read_csv('rezultate/calib_ratio/harmonized_regionmonth.csv'); H=H[(H.daynight=='D')&H.year.between(2012,2021)]
R=['SHSA','SHAF','BOAS','SEAS']; fig,ax=plt.subplots(4,2,figsize=(14,13),sharex=True)
t=lambda d: d.year+(d.month-0.5)/12
for i,r in enumerate(R):
    a=A[(A.region==r)&(A.satellite=='Aqua')].sort_values(['year','month']); v=A[(A.region==r)&(A.satellite=='SNPP')].sort_values(['year','month']); h=H[H.region==r].sort_values(['year','month'])
    for j,(var,lab) in enumerate((('n','fire pixels / month (log)'),('frp','summed FRP, MW / month'))):
        x=ax[i,j]; x.plot(t(a),a[var],c='#1f77b4',lw=1.3,label='Aqua MODIS (real)'); x.plot(t(v),v[var],c='#bbbbbb',lw=1,label='S-NPP VIIRS raw')
        x.plot(t(h),h[f'pred_{var}'],c='#d62728',lw=1.1,ls='--',label='VIIRS harmonized (Aqua-equiv.)')
        x.fill_between(t(h),h[f'lo_{var}'],h[f'hi_{var}'],color='#d62728',alpha=.15,lw=0)
        x.axvspan(2018,2022,color='k',alpha=.05); x.set_title(f'{r} daytime - {lab}',fontsize=10)
        if var=='n': x.set_yscale('log')
        if i==0 and j==0: x.legend(fontsize=8,loc='lower left')
fig.text(.5,.005,'shaded = test period 2018-2021 (not used for calibration); band = 10-90% interval',ha='center',fontsize=9)
fig.tight_layout(rect=(0,.015,1,1)); fig.savefig('rezultate/calib_ratio/fig_before_after.png',dpi=110)
M=A.pivot_table(index=['region','year','month'],columns='satellite',values=['n','frp']).reset_index(); M.columns=['region','year','month','frp_aqua','frp_snpp','n_aqua','n_snpp']
M=M.merge(H[['region','year','month','pred_n','pred_frp']],on=['region','year','month'])
pd.set_option('display.width',200); print(M[M.region.isin(R)&(M.year==2019)&M.month.isin([8,9])].round(0).to_string(index=False))
