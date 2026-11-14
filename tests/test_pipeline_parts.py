"""Processing in parts: --paired-only per half / per year, then --from-paired on the
concatenation, must equal one pass over the union of the inputs (countries in disjoint
tiles, so no border cells)."""
import json

import numpy as np
import pandas as pd
import pytest

from harmonize import pipeline
from harmonize.config import Config

MODIS_HDR = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
             "confidence,version,bright_t31,frp,daynight,type")
VIIRS_HDR = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
             "confidence,version,bright_ti5,frp,daynight,type")
# country -> (lat0, lon0, true VIIRS/MODIS detection ratio); 20-30 deg apart, so no shared tile
COUNTRIES = {"Alpha": (40.0, 10.0, 3), "Beta": (-15.0, -50.0, 2),
             "Gamma": (60.0, 100.0, 4), "Delta": (10.0, 20.0, 3)}
HALVES = {"A": ("Alpha", "Beta"), "B": ("Gamma", "Delta")}
YEARS = (2019, 2020)


def _rows(country, year, rng):
    lat0, lon0, k = COUNTRIES[country]
    m, v = [], []
    # every source detects something on the first and last day of the year, as in real
    # yearly data (a source's coverage window is clipped to its observed span in the run)
    edges = [(f"{year}-01-01", s) for s in ("Terra", "Aqua")] + \
            [(f"{year}-12-31", s) for s in ("Terra", "Aqua")]
    for i in range(150 + len(edges)):
        lat, lon = lat0 + rng.uniform(0, 3), lon0 + rng.uniform(0, 3)
        day = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(days=int(rng.integers(0, 365)))
        d = day.strftime("%Y-%m-%d")
        dn = "D" if rng.random() < 0.7 else "N"
        sat = "Terra" if rng.random() < 0.5 else "Aqua"
        if i >= 150:
            d, sat = edges[i - 150]
        frp = rng.gamma(2.0, 15.0)
        m.append(f"{lat:.4f},{lon:.4f},320.5,1.2,1.1,{d},1030,{sat},MODIS,"
                 f"{int(rng.integers(30, 100))},6.03,290.1,{frp:.2f},{dn},0")
        for _ in range(k):
            v.append(f"{lat + rng.normal(0, 0.01):.5f},{lon + rng.normal(0, 0.01):.5f},330.0,"
                     f"0.4,0.4,{d},1330,N,VIIRS,n,2,290.0,{frp / k:.2f},{dn},0")
    return m, v


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    root = tmp_path_factory.mktemp("parts")
    rng = np.random.default_rng(7)
    for half, countries in HALVES.items():
        for y in YEARS:
            for c in countries:
                m, v = _rows(c, y, rng)
                for d in (root / half / str(y), root / "union" / str(y)):
                    d.mkdir(parents=True, exist_ok=True)
                    (d / f"modis_{y}_{c}.csv").write_text("\n".join([MODIS_HDR, *m]) + "\n")
                    (d / f"viirs-snpp_{y}_{c}.csv").write_text("\n".join([VIIRS_HDR, *v]) + "\n")
    return root


def _cfg(root, data_dir, out_dir):
    return Config(data_dir=root / data_dir, out_dir=root / "out" / out_dir,
                  cache_dir=root / "cache")


KEY = ["modis_source", "cell_id", "period", "daynight"]


def _sorted(df):
    df = df.copy()
    for c in df.columns:
        if isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].astype(str)
    return df.sort_values(KEY).reset_index(drop=True)[sorted(df.columns)]


def _close(a, b, path):
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), path
        for k in a:
            _close(a[k], b[k], (path, k))
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, (path, i))
    elif isinstance(a, float) or isinstance(b, float):
        assert a == pytest.approx(b, rel=1e-7, abs=1e-9, nan_ok=True), path
    else:
        assert a == b, path


def test_parts_equal_union(data):
    parts = []
    for half in HALVES:
        for y in YEARS:
            res = pipeline.run(_cfg(data, f"{half}/{y}", f"{half}_{y}"), paired_only=True)
            out = data / "out" / f"{half}_{y}"
            assert (out / "paired.parquet").exists() and (out / "coverage.parquet").exists()
            assert not (out / "hotspots_clean.parquet").exists()
            assert not (out / "calibration_coefficients.json").exists()
            assert set(res) == {"paired", "coverage"}
            parts.append(out / "paired.parquet")
    pipeline.run(_cfg(data, "union", "union_paired"), paired_only=True)
    union = pd.read_parquet(data / "out" / "union_paired" / "paired.parquet")
    concat = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    a, b = _sorted(concat), _sorted(union)
    assert len(a) == len(b) > 0
    pd.testing.assert_frame_equal(a, b, check_dtype=False)

    # --from-paired on the parts gives the coefficients of a single full pass
    full = pipeline.run(_cfg(data, "union", "union_full"), skip_validation=True, plots=False)
    fp = pipeline.run_from_paired(_cfg(data, "union", "from_parts"), parts,
                                  skip_validation=True, plots=False)
    ca = {(c["metric"], c["model"], c["modis_source"], c["daynight"]): c["params"]
          for c in full["coef"]["coefficients"]}
    cb = {(c["metric"], c["model"], c["modis_source"], c["daynight"]): c["params"]
          for c in fp["coef"]["coefficients"]}
    assert ca.keys() == cb.keys() and len(ca) > 0
    for k in ca:   # equal up to float summation order (rows arrive in a different order)
        _close(json.loads(json.dumps(ca[k], default=str)),
               json.loads(json.dumps(cb[k], default=str)), k)
    assert full["coef"]["recommended"]["metric"] == fp["coef"]["recommended"]["metric"]
    assert (data / "out" / "from_parts" / "calibration_coefficients.json").exists()


def test_cli_rejects_bad_combinations(data):
    with pytest.raises(SystemExit):
        pipeline.main(["--paired-only", "--from-paired", "x.parquet"])
    with pytest.raises(SystemExit):
        pipeline.main(["--from-paired", "x.parquet", "--coefficients", "c.json"])
