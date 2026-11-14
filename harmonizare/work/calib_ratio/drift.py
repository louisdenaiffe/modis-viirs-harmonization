import sys; sys.path.insert(0,'work/calib_ratio'); from lib import *
from scipy import stats
c=con(); P=f"read_parquet('{W}/pair_*.parquet')"
y=c.execute(f"SELECT daynight, year, sum(a_n)/sum(s_n) rn, sum(a_frp)/sum(s_frp) rf, sum(a_n) an FROM {P} WHERE (year*12+month)>=2012*12+2 AND NOT (year=2020 AND month IN (8,9)) GROUP BY ALL ORDER BY 1,2").df()
print(y.round(4).to_string())
for dn in 'DN':
    for col in ('rn','rf'):
        g=y[(y.daynight==dn)&(y.year<=2017)]; lr=stats.linregress(g.year,np.log(g[col]))
        cal=g[col].mean(); t=y[(y.daynight==dn)&(y.year>=2018)][col].mean()
        print(dn,col,'cal-years trend %/yr',round(100*lr.slope,2),'p',round(lr.pvalue,3),'cal sd of log ratio',round(np.log(g[col]).std(),3),
              'test mean/cal mean -1 (%)',round(100*(t/cal-1),2),'extrapolated trend to 2019.5 (%)',round(100*lr.slope*(2019.5-2014.5),2))
# regionally: fraction of regions whose test-year ratio is below cal mean (day counts)
r=c.execute(f"SELECT region, year>=2018 test, sum(a_n)/sum(s_n) r FROM {P} WHERE daynight='D' AND region<>'OTHR' AND (year*12+month)>=2012*12+2 AND NOT (year=2020 AND month IN (8,9)) GROUP BY ALL").df().pivot(index='region',columns='test',values='r')
r['chg%']=100*(r[True]/r[False]-1); print(r.round(3).to_string()); print('regions with lower ratio in test:',(r['chg%']<0).sum(),'/',len(r))
