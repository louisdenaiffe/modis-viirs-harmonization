import sys, time; sys.path.insert(0,'work/calib_ratio'); from lib import *
T0=time.time(); name=sys.argv[1]; n0=dict(a.split('=') for a in sys.argv[2:])
fit = load(*CAL); tgt = load(*TEST); tgt = tgt[(tgt.s_n > 0)]
CHS={'B1':[['region']], 'B2':[['region'],['region','season']], 'B3':[['region'],['b2'],['cell']]}
if name[:2]=='B5':
    N0={'n':(3000,1000),'frp':(1000,10000)}; K={}
    for var in ('n','frp'):
        K[var]=hier_factors(fit,tgt,CHS['B2'],var,[0,N0[var][0]])*hier_factors(fit,tgt,CHS['B3'],var,[0,N0[var][1],N0[var][1]])/hier_factors(fit,tgt,CHS['B1'],var,[0])
    p=to_pred(tgt,K['n'],K['frp']); print(ec.evaluate(p, f'CR_{name}', notes='calib_ratio region-season factor x (cell->2deg->region shrunk factor / region factor); n0 n 3000/1000 frp 1000/10000').drop(columns=['notes','time']).to_string()); sys.exit()
CH={'B1':[['region']], 'B2':[['region'],['region','season']], 'B3':[['region'],['b2'],['cell']]}[name[:2]]
def n0s(var):
    v=[1e9 if i==0 and name[:2]!='B1' else 0 for i in range(len(CH))]  # region level: unshrunk ratio (region sums are large)
    v=[0]+[float(n0.get(var,0))]*(len(CH)-1); return v
kn=hier_factors(fit,tgt,CH,'n',n0s('n')); kf=hier_factors(fit,tgt,CH,'frp',n0s('frp'))
p=to_pred(tgt,kn,kf); print('pred built',round(time.time()-T0,1),flush=True)
print(ec.evaluate(p, f'CR_{name}', notes=f'calib_ratio {CH} n0={n0}').drop(columns=['notes','time']).to_string()); print('t',round(time.time()-T0,1))
