import sys, time, pandas as pd; sys.path.insert(0, 'scripts'); import eval_common as ec
f, label, notes = sys.argv[1:4]; t0 = time.time()
p = pd.read_parquet(f); r = ec.evaluate(p, label, notes=notes)
print(r.drop(columns=['notes', 'time']).to_string(), round(time.time() - t0, 1))
