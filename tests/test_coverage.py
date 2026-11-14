import copy

import numpy as np
import pandas as pd

from harmonize.config import Config
from harmonize.coverage import (CoverageIndex, build_coverage, covered_day_counts, tag_points,
                                tile_codes)


def pts(rows):
    """rows: (source_file, source, lat, lon, 'YYYY-MM-DD')"""
    df = pd.DataFrame(rows, columns=["source_file", "source", "latitude", "longitude", "acq_date"])
    for c in ("source_file", "source", "acq_date"):
        df[c] = df[c].astype("category")
    return df


def flags(tagged):
    return list(zip(tagged["viirs_covered"], tagged["terra_covered"], tagged["aqua_covered"],
                    tagged["modis_config"].astype(str)))


def test_build_coverage_rows_and_ranges():
    cfg = Config(coverage_tile_deg=1.0)
    raw = pts([("m.csv", "MODIS_TERRA", 40.5, 10.5, "2025-01-03"),
               ("m.csv", "MODIS_TERRA", 41.5, 10.5, "2025-01-20"),
               ("m.csv", "MODIS_AQUA", 40.5, 10.5, "2025-01-05"),
               ("v.csv", "VIIRS_SNPP", 40.2, 10.9, "2025-01-10"),
               ("m2.csv", "MODIS_AQUA", -10.5, 10.5, "2025-01-25")])   # widens Aqua's span
    cov = build_coverage(raw, cfg)
    assert list(cov.columns) == ["source_file", "source", "cov_tile", "date_min", "date_max"]
    assert len(cov) == 5
    t = cov.set_index(["source", "cov_tile"])
    # one file covers every tile it touches over the file's full date range
    assert str(t.loc[("MODIS_TERRA", "130_190"), "date_min"].date()) == "2025-01-03"
    assert str(t.loc[("MODIS_TERRA", "131_190"), "date_min"].date()) == "2025-01-03"
    assert str(t.loc[("MODIS_AQUA", "130_190"), "date_max"].date()) == "2025-01-20"
    assert str(t.loc[("VIIRS_SNPP", "130_190"), "date_min"].date()) == "2025-01-10"
    # ... clipped to the source's observed span over all files (here VIIRS: a single day)
    assert str(t.loc[("VIIRS_SNPP", "130_190"), "date_max"].date()) == "2025-01-10"


def test_terra_only_and_aqua_mission_window():
    """A Terra+Aqua file in which Aqua starts mid-year: before Aqua's first data the tile-days are
    Terra-only (the source's observed span clips the file range)."""
    cfg = Config()
    raw = pts([("m.csv", "MODIS_TERRA", 40.5, 10.5, "2002-01-01"),
               ("m.csv", "MODIS_TERRA", 40.5, 10.5, "2002-12-31"),
               ("m.csv", "MODIS_AQUA", 40.5, 10.5, "2002-07-04"),
               ("m.csv", "MODIS_AQUA", 40.5, 10.5, "2002-12-30")])
    tagged = tag_points(raw, build_coverage(raw, cfg), cfg)
    assert flags(tagged) == [(False, True, False, "MODIS_TERRA"), (False, True, False, "MODIS_TERRA"),
                             (False, True, True, "MODIS_ALL"), (False, True, True, "MODIS_ALL")]


def test_tag_points_spatial_and_daily():
    cfg = Config()
    raw = pts([("modis_X.csv", "MODIS_TERRA", 45.5, 10.5, "2025-07-01"),
               ("modis_X.csv", "MODIS_AQUA", 45.5, 10.5, "2025-07-31"),
               ("modis_Z.csv", "MODIS_TERRA", 0.5, 0.5, "2025-07-31"),
               ("modis_Z.csv", "MODIS_AQUA", 0.5, 0.5, "2025-07-01"),
               ("viirs_Y.csv", "VIIRS_SNPP", 38.5, 22.5, "2025-07-15"),
               ("viirs_Y.csv", "VIIRS_SNPP", 38.5, 22.5, "2025-07-20")])
    tagged = tag_points(raw, build_coverage(raw, cfg), cfg)
    # MODIS tile is never VIIRS covered, VIIRS tile is never MODIS covered (v1 bug 1)
    assert flags(tagged)[:2] + flags(tagged)[4:] == [
        (False, True, True, "MODIS_ALL"), (False, True, True, "MODIS_ALL"),
        (True, False, False, "NONE"), (True, False, False, "NONE")]
    assert tagged["cov_tile"].astype(str).tolist() == ["135_190", "135_190", "90_180", "90_180",
                                                       "128_202", "128_202"]
    # probe points: VIIRS covers its tile 07-15..07-20 only
    probe = pts([("p", "X", 38.5, 22.5, d) for d in ("2025-07-14", "2025-07-15", "2025-07-20",
                                                      "2025-07-21")])
    t2 = tag_points(probe, build_coverage(raw, cfg), cfg)
    assert t2["viirs_covered"].tolist() == [False, True, True, False]


def test_union_of_intervals_across_files():
    cfg = Config()
    raw = pts([("a.csv", "VIIRS_SNPP", 40.5, 10.5, "2025-01-01"),
               ("a.csv", "VIIRS_SNPP", 40.5, 10.5, "2025-01-10"),
               ("b.csv", "VIIRS_SNPP", 40.5, 10.5, "2025-01-20"),
               ("b.csv", "VIIRS_SNPP", 40.5, 10.5, "2025-01-31")])
    cov = build_coverage(raw, cfg)
    probe = pts([("p", "X", 40.5, 10.5, d) for d in
                 ("2025-01-05", "2025-01-15", "2025-01-25", "2025-02-01")])
    assert tag_points(probe, cov, cfg)["viirs_covered"].tolist() == [True, False, True, False]
    idx = CoverageIndex(cov, cfg)
    tile = tile_codes([40.5], [10.5], 1.0)
    cnt = covered_day_counts(tile, np.array([202501]), cfg, index=idx)
    assert int(cnt["n_viirs"].iloc[0]) == 22   # 10 + 12 days


def test_index_survives_filter_copy_and_concat():
    cfg = Config()
    raw = pts([("a.csv", "VIIRS_SNPP", 40.5, 10.5, "2025-01-01"),
               ("a.csv", "VIIRS_SNPP", 40.5, 10.5, "2025-01-10")])
    t = tag_points(raw, build_coverage(raw, cfg), cfg)
    idx = t.attrs["coverage_index"]
    assert t.iloc[:1].attrs["coverage_index"] is idx
    assert copy.deepcopy(t).attrs["coverage_index"] is idx
    assert pd.concat([t.iloc[:1], t.iloc[1:]]).attrs["coverage_index"] is idx


def test_vectorized_scale():
    cfg = Config()
    n = 200_000
    rng = np.random.default_rng(0)
    days = pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D")
    raw = pd.DataFrame({
        "source_file": pd.Categorical(rng.choice(["a", "b", "c"], n)),
        "source": pd.Categorical(rng.choice(["MODIS_TERRA", "MODIS_AQUA", "VIIRS_SNPP"], n)),
        "latitude": rng.uniform(-60, 70, n), "longitude": rng.uniform(-180, 180, n),
        "acq_date": pd.Categorical(days.strftime("%Y-%m-%d")),
    })
    import time
    t0 = time.perf_counter()
    tagged = tag_points(raw, build_coverage(raw, cfg), cfg)
    assert time.perf_counter() - t0 < 10
    assert tagged["modis_config"].isin(["MODIS_ALL", "MODIS_TERRA", "MODIS_AQUA", "NONE"]).all()
    # each point is covered by its own source
    own = np.select([raw["source"] == "VIIRS_SNPP", raw["source"] == "MODIS_TERRA"],
                    [tagged["viirs_covered"], tagged["terra_covered"]], tagged["aqua_covered"])
    assert own.all()
