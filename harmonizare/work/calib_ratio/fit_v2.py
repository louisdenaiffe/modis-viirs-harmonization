import sys; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model_v2 as am2
cal=load(*CAL,extra=', s_nb'); F=am2.fit_factors_v2(cal)
I=pd.read_parquet('rezultate/calib_ratio/factors.parquet'); I=I[I.level.str.startswith('interval')]
F=pd.concat([F,I],ignore_index=True); F.to_parquet('rezultate/calib_ratio/factors_v2.parquet'); F.to_csv('rezultate/calib_ratio/factors_v2.csv',index=False)
print(F[F['var']=='n_best_hilat'].groupby(['level','region']).k.agg(['count','median']).round(3).to_string())
t=load(*TEST,extra=', s_nb'); t=t[t.s_n>0]
df=t[['ix','iy','year','month','daynight','s_n','s_frp','s_nb']].rename(columns={'s_n':'n_sum','s_frp':'frp_sum','s_nb':'n_best'})
p=am2.predict(df,F)
print(ec.evaluate(p[ec.KEYS+['pred_n','pred_frp']],'CR_V2_B5_nbest_lat60_BO',notes='v2: B5 + BONA/BOAS day counts from n_best, split at 60N').drop(columns=['notes','time']).to_string())
print(pd.read_csv('rezultate/eval/CR_V2_B5_nbest_lat60_BO_n_D_regions.csv').round(3).to_string())
