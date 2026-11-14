import duckdb, numpy as np, pandas as pd
W='work/calib_ratio'
c = duckdb.connect(); c.execute("SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='data/_ducktmp/calib_ratio'")
P=f"read_parquet('{W}/pair_*.parquet')"
CAL="(year*12+month) BETWEEN 2012*12+2 AND 2017*12+12"
mets={'n_sum':('a_n','s_n'),'frp_sum':('a_frp','s_frp'),'n_best':('a_nb','s_nb'),'frp_best':('a_fb','s_fb'),'nsub_best':('a_sb','s_sb'),'days':('a_d','s_d'),'active_cells':('(a_n>0)::INT','(s_n>0)::INT')}
rows=[]
for k,(a,s) in mets.items():
  q=f"""WITH k AS (SELECT region,daynight, sum({a})::DOUBLE/sum({s}) kr FROM {P} WHERE {CAL} GROUP BY ALL),
   x AS (SELECT p.*, kr, {a} av, {s}*kr pv FROM {P} p JOIN k USING(region,daynight) WHERE {CAL}),
   cm AS (SELECT daynight, sum(abs(av-pv))/sum(av) cell_nmae, median(CASE WHEN av>0 AND pv>0 THEN abs(ln(av/pv)) END) cell_logscat FROM x GROUP BY ALL),
   rm AS (SELECT daynight, region, year, month, sum(av) av, sum(pv) pv FROM x GROUP BY ALL),
   rmm AS (SELECT daynight, sum(abs(av-pv))/sum(av) regmonth_nmae, median(CASE WHEN av>=50 AND pv>0 THEN abs(ln(av/pv)) END) regmonth_logscat FROM rm WHERE region<>'OTHR' GROUP BY ALL)
   SELECT '{k}' metric, * FROM cm JOIN rmm USING (daynight)"""
  rows.append(c.execute(q).df())
R=pd.concat(rows).round(3).sort_values(['daynight','metric'])
print(R.to_string(index=False))
R.to_csv('rezultate/calib_ratio/partA_scatter_after_regional_ratio.csv',index=False)
