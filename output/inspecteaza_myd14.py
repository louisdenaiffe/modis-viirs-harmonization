#!/usr/bin/env python3
"""Inspect MYD14 whole swaths; class counts are NOT Albania-only."""
import csv, datetime, pathlib
import numpy as np
from pyhdf.SD import SD, SDC
base=pathlib.Path(__file__).resolve().parent
files=sorted((base/'MYD14_Albania_2024').glob('MYD14.A20242*.hdf'))
rows=[]
for path in files:
    h=SD(str(path),SDC.READ)
    try:
        mask=h.select('fire mask').get()
        vals=np.bincount(mask.ravel().astype(np.int64),minlength=10)
        if len(vals)>10 and vals[10:].sum(): raise ValueError('Mask contains unexpected classes')
        tag=path.name.split('.')[1]; day=datetime.datetime.strptime(tag[1:],'%Y%j').date().isoformat()
        rows.append(dict(file=path.name,date_utc=day,time_utc=path.name.split('.')[2],pixels=mask.size,missing=int(vals[0]+vals[1]+vals[2]),water=int(vals[3]),cloud=int(vals[4]),land_no_fire=int(vals[5]),unknown=int(vals[6]),fire_low=int(vals[7]),fire_nominal=int(vals[8]),fire_high=int(vals[9])))
    finally: h.end()
out=base/'rezumat_masti_MYD14.csv'
with out.open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print('Files:',len(rows));print('Range:',rows[0]['date_utc'],rows[-1]['date_utc']);print('Total pixels:',sum(r['pixels'] for r in rows))
for c in ['missing','water','cloud','land_no_fire','unknown','fire_low','fire_nominal','fire_high']:
 print(c,sum(r[c] for r in rows))
print('CSV:',out)
