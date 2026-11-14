import duckdb, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
W = f'{ROOT}/work/simul_overpass'; R = f'{ROOT}/rezultate/simul_overpass'
def con(mem='600MB'):
    c = duckdb.connect()
    os.makedirs(f'{ROOT}/data/_ducktmp/simul_overpass', exist_ok=True)
    c.execute(f"SET memory_limit='{mem}'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='{ROOT}/data/_ducktmp/simul_overpass'")
    return c
