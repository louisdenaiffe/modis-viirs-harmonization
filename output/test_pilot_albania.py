#!/usr/bin/env python3
"""Exploratory FIRMS comparison. No cloud/coverage information; not a validated harmonization."""
import csv, math, json
from pathlib import Path
from collections import defaultdict
P = Path(__file__).resolve().parent
# Lambert azimuthal equal-area projection, centered on Albania, 5 km cells.
def cell(lat, lon):
    lat, lon, lat0, lon0 = map(math.radians, (float(lat), float(lon), 41.0, 20.0))
    dl = lon-lon0
    k=math.sqrt(2/(1+math.sin(lat0)*math.sin(lat)+math.cos(lat0)*math.cos(lat)*math.cos(dl)))
    x=6371008.8*k*math.cos(lat)*math.sin(dl)
    y=6371008.8*k*(math.cos(lat0)*math.sin(lat)-math.sin(lat0)*math.cos(lat)*math.cos(dl))
    return math.floor(x/5000),math.floor(y/5000)
def load(name, satellite):
    groups=defaultdict(set); stats=defaultdict(int)
    with (P/name).open(newline='') as f:
        for row in csv.DictReader(f):
            stats['all']+=1
            if row['satellite'] != satellite or row.get('type') != '0': continue
            stats['included']+=1
            date=row['acq_date']; month=int(date[5:7])
            groups[month].add((date, row['daynight'], *cell(row['latitude'],row['longitude'])))
    return {m:len(groups[m]) for m in range(1,13)},dict(stats)
a,sa=load('modis_2024_Albania.csv','Aqua')
v,sv=load('viirs-snpp_2024_Albania.csv','N')
train=[1,3,5,7,9,11]; test=[2,4,6,8,10,12]
# Least squares through zero. Scaling is illustrative; no coverage is available.
factor=sum(v[m]*a[m] for m in train)/sum(v[m]**2 for m in train)
def metrics(predict):
    err=[predict(m)-a[m] for m in test]
    return {'MAE':sum(map(abs,err))/len(err),'bias':sum(err)/len(err)}
result={'description':'Exploratory counts of detected 5 km cell-UTC-day-daynight combinations, not fire counts or observable zeros', 'training_months':train,'test_months':test,'factor':factor,'stats_modis':sa,'stats_viirs':sv,'baseline_raw_viirs_test':metrics(lambda m:v[m]),'factor_test':metrics(lambda m:factor*v[m]),'months':[{'month':m,'modis_aqua':a[m],'viirs_snpp':v[m],'predicted_modis':round(factor*v[m],2),'split':'train' if m in train else 'test'} for m in range(1,13)],'limitations':['one country and year','CSV detections only; no cloud, coverage, or true observable zeros','different overpass times and imperfect observations','includes monthly zero recorded detections, not known no-fire months','split does not test transfer to another year or region','all 2024 observations in same country; seasonal and spatial dependence','type 0 is presumed vegetation, not confirmed ground truth']}
with (P/'rezultate_pilot_albania.json').open('w') as f: json.dump(result,f,indent=2)
print(json.dumps(result,indent=2))
