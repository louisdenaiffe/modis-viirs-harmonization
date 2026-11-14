import sys; sys.path.insert(0,'work/calib_ratio'); sys.path.insert(0,'rezultate/calib_ratio'); from lib import *
import apply_model as am
cal=load(*CAL); F=am.fit_factors(cal[['ix','iy','year','month','daynight','a_n','a_frp','s_n','s_frp']])
F.to_parquet('work/calib_ratio/factors_noint.parquet'); print(F.groupby(['level','var','daynight']).k.describe().round(3).to_string())
tgt=load(*TEST); tgt=tgt[tgt.s_n>0]; df=tgt[['ix','iy','year','month','daynight','s_n','s_frp']].rename(columns={'s_n':'n_sum','s_frp':'frp_sum'})
p=am.predict(df,F,interval=False); print(ec.evaluate(p,'CR_B5_prod_check',notes='apply_model.py reproduction of B5',write=False).drop(columns=['notes','time']).to_string())
