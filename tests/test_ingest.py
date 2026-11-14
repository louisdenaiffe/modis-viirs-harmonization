import os
import zipfile

import pandas as pd
import pytest

from harmonize import ingest
from harmonize.config import Config
from harmonize.ingest import (POINT_COLUMNS, apply_filters, detect_sensor, domain_from_filename,
                              load_points)

MODIS_HDR = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
             "confidence,version,bright_t31,frp,daynight,type")
VIIRS_HDR = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
             "confidence,version,bright_ti5,frp,daynight,type")


def modis_row(lat=40.0, lon=10.0, date="2025-07-01", time="136", sat="Terra", conf=50,
              dn="D", typ=0, frp=10.0):
    return f"{lat},{lon},320.5,1.0,1.0,{date},{time},{sat},MODIS,{conf},61.03,290.1,{frp},{dn},{typ}"


def viirs_row(lat=40.0, lon=10.0, date="2025-07-01", time="0136", sat="N", conf="n",
              dn="N", typ=0, frp=2.0):
    return f"{lat},{lon},330.0,0.4,0.4,{date},{time},{sat},VIIRS,{conf},2,290.0,{frp},{dn},{typ}"


def write(tmp_path, name, hdr, rows):
    (tmp_path / name).write_text("\n".join([hdr, *rows]) + "\n")


def cfg_for(tmp_path, **kw):
    return Config(data_dir=tmp_path, out_dir=tmp_path / "out", cache_dir=tmp_path.parent /
                  f"{tmp_path.name}_cache", **kw)


def test_detect_sensor():
    assert detect_sensor(MODIS_HDR.split(",")) == "MODIS"
    assert detect_sensor(VIIRS_HDR.split(",")) == "VIIRS"
    with pytest.raises(ValueError):
        detect_sensor(["latitude", "longitude"])


def test_sensor_detected_from_columns_not_filename(tmp_path):
    write(tmp_path, "viirs_named_but_modis.csv", MODIS_HDR, [modis_row()])
    write(tmp_path, "zzz.csv", VIIRS_HDR, [viirs_row()])
    p = load_points(cfg_for(tmp_path))
    assert list(p.columns) == POINT_COLUMNS
    assert p.set_index("source_file")["sensor"].to_dict() == {
        "viirs_named_but_modis.csv": "MODIS", "zzz.csv": "VIIRS"}


def test_acq_time_int_and_padded(tmp_path):
    write(tmp_path, "m.csv", MODIS_HDR, [modis_row(time="136"), modis_row(time="5", conf=51)])
    write(tmp_path, "v.csv", VIIRS_HDR, [viirs_row(time="0136"), viirs_row(time="2359")])
    p = load_points(cfg_for(tmp_path))
    assert str(p["datetime_utc"].dtype) == "datetime64[ns, UTC]"
    got = p["datetime_utc"].dt.strftime("%Y-%m-%d %H:%M").tolist()
    assert got == ["2025-07-01 01:36", "2025-07-01 00:05", "2025-07-01 01:36", "2025-07-01 23:59"]
    assert p["acq_time"].tolist() == [136, 5, 136, 2359]
    assert p["acq_date"].tolist() == ["2025-07-01"] * 4


def test_modis_confidence_boundaries(tmp_path):
    write(tmp_path, "m.csv", MODIS_HDR, [modis_row(conf=c) for c in (0, 29, 30, 79, 80, 100)])
    p = load_points(cfg_for(tmp_path))
    assert p["confidence_class"].tolist() == ["low", "low", "nominal", "nominal", "high", "high"]
    assert p["confidence_raw"].tolist() == ["0", "29", "30", "79", "80", "100"]
    # thresholds are configurable
    p2 = load_points(cfg_for(tmp_path, modis_conf_low_max=30, modis_conf_high_min=79))
    assert p2["confidence_class"].tolist() == ["low", "low", "low", "high", "high", "high"]


def test_viirs_confidence_mapping(tmp_path):
    write(tmp_path, "v.csv", VIIRS_HDR, [viirs_row(conf=c) for c in ("l", "n", "h", "H", "L")])
    p = load_points(cfg_for(tmp_path))
    assert p["confidence_class"].tolist() == ["low", "nominal", "high", "high", "low"]


def test_satellite_to_source(tmp_path):
    write(tmp_path, "m.csv", MODIS_HDR, [modis_row(sat="Terra"), modis_row(sat="Aqua")])
    write(tmp_path, "v.csv", VIIRS_HDR,
          [viirs_row(sat=s) for s in ("N", "1", "N20", "2", "N21")])
    p = load_points(cfg_for(tmp_path))
    assert p["source"].tolist() == ["MODIS_TERRA", "MODIS_AQUA", "VIIRS_SNPP", "VIIRS_NOAA20",
                                    "VIIRS_NOAA20", "VIIRS_NOAA21", "VIIRS_NOAA21"]
    assert p["satellite_raw"].tolist() == ["Terra", "Aqua", "N", "1", "N20", "2", "N21"]


def test_unknown_satellite_raises(tmp_path):
    write(tmp_path, "v.csv", VIIRS_HDR, [viirs_row(sat="XYZ")])
    with pytest.raises(ValueError):
        load_points(cfg_for(tmp_path))


def test_brightness_columns_mapped(tmp_path):
    write(tmp_path, "m.csv", MODIS_HDR, [modis_row()])
    write(tmp_path, "v.csv", VIIRS_HDR, [viirs_row()])
    p = load_points(cfg_for(tmp_path))
    assert p["bright_mir_k"].tolist() == [320.5, 330.0]
    assert p["bright_tir_k"].tolist() == pytest.approx([290.1, 290.0])  # float32


def test_missing_type_column_defaults_to_zero(tmp_path):
    hdr = VIIRS_HDR.rsplit(",", 1)[0]
    row = viirs_row().rsplit(",", 1)[0]
    write(tmp_path, "nrt.csv", hdr, [row])
    p = load_points(cfg_for(tmp_path))
    assert p["type"].tolist() == [0]


def test_filters_type_and_confidence_configurable(tmp_path):
    # distinct positions: identical (source, lat, lon, time) would be de-duplicated
    rows = [viirs_row(lat=40.1, conf="l"), viirs_row(lat=40.2, conf="n"), viirs_row(lat=40.3, conf="h"),
            viirs_row(lat=40.4, conf="h", typ=2), viirs_row(lat=40.5, conf="n", typ=3)]
    write(tmp_path, "v.csv", VIIRS_HDR, rows)
    cfg = cfg_for(tmp_path)
    p = load_points(cfg)
    f = apply_filters(p, cfg)  # default: type 0, >= nominal
    assert sorted(f["confidence_class"]) == ["high", "nominal"]
    assert set(f["type"]) == {0}
    f = apply_filters(p, cfg_for(tmp_path, min_confidence="low", keep_types=(0, 2, 3)))
    assert len(f) == 5
    f = apply_filters(p, cfg_for(tmp_path, min_confidence="high", keep_types=(0, 2)))
    assert sorted(f["type"]) == [0, 2]


def test_overlapping_files_deduplicated(tmp_path):
    write(tmp_path, "a.csv", VIIRS_HDR, [viirs_row(), viirs_row(lat=41.0)])
    write(tmp_path, "b.csv", VIIRS_HDR, [viirs_row(lat=41.0), viirs_row(lat=42.0)])
    cfg = cfg_for(tmp_path)
    p = load_points(cfg)
    assert len(p) == 4  # unfiltered table keeps everything
    f = apply_filters(p, cfg)
    assert sorted(f["latitude"]) == [40.0, 41.0, 42.0]


def test_no_files_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_points(cfg_for(tmp_path))


def test_overlap_dedupe_ignores_other_columns(tmp_path):
    # same detection in two country files; a non-key column differs (version) -> still one point
    write(tmp_path, "modis_2019_A.csv", MODIS_HDR, [modis_row(lat=41.5, lon=20.0, frp=5.0)])
    write(tmp_path, "modis_2019_B.csv", MODIS_HDR,
          [modis_row(lat=41.5, lon=20.0, frp=5.0).replace("61.03", "61.04"),
           modis_row(lat=41.5, lon=20.0, sat="Aqua")])   # other source -> kept
    cfg = cfg_for(tmp_path)
    f = apply_filters(load_points(cfg), cfg)
    assert len(f) == 2
    assert f["source"].astype(str).tolist() == ["MODIS_TERRA", "MODIS_AQUA"]
    assert f["source_file"].astype(str).tolist() == ["modis_2019_A.csv", "modis_2019_B.csv"]


def test_dtypes_compact(tmp_path):
    write(tmp_path, "m.csv", MODIS_HDR, [modis_row()])
    write(tmp_path, "v.csv", VIIRS_HDR, [viirs_row()])
    p = load_points(cfg_for(tmp_path))
    assert p["latitude"].dtype == "float64" and p["longitude"].dtype == "float64"
    for c in ("frp", "scan", "track", "bright_mir_k", "bright_tir_k"):
        assert p[c].dtype == "float32", c
    for c in ("source", "sensor", "daynight", "confidence_class", "source_file", "domain", "acq_date"):
        assert isinstance(p[c].dtype, pd.CategoricalDtype), c
    # categories survive concatenation of files with different category sets
    assert set(p["source"].astype(str)) == {"MODIS_TERRA", "VIIRS_SNPP"}


def test_load_columns_subset(tmp_path):
    write(tmp_path, "v.csv", VIIRS_HDR, [viirs_row()])
    cfg = cfg_for(tmp_path)
    for _ in range(2):  # cold, then from cache
        p = load_points(cfg, columns=["latitude", "source", "frp"])
        assert list(p.columns) == ["source", "latitude", "frp"]
    with pytest.raises(ValueError):
        load_points(cfg, columns=["nope"])


@pytest.mark.parametrize("name,expected", [
    ("modis_2019_United_States.csv", "United_States"),
    ("viirs-snpp_2012_Greece.csv", "Greece"),
    ("fire_archive_M-C61_12345.csv", "fire_archive_M-C61_12345"),
    ("J1_VIIRS_C2_Global_7d.csv", "Global"),
    ("sub/dir/modis_2023_Kazakhstan.csv", "Kazakhstan"),
    ("all.zip/viirs-snpp_2019_Brazil.csv", "Brazil"),
])
def test_domain_from_filename(name, expected):
    assert domain_from_filename(name) == expected


def test_domain_column(tmp_path):
    write(tmp_path, "modis_2019_United_States.csv", MODIS_HDR, [modis_row()])
    p = load_points(cfg_for(tmp_path))
    assert p["domain"].astype(str).tolist() == ["United_States"]


def test_recursive_and_zip(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    write(tmp_path / "a" / "b", "modis_2019_X.csv", MODIS_HDR, [modis_row()])
    with zipfile.ZipFile(tmp_path / "bundle.zip", "w") as zf:
        zf.writestr("viirs-snpp_2019_Y.csv", "\n".join([VIIRS_HDR, viirs_row(), viirs_row(lat=41.0)]))
        zf.writestr("viirs-snpp_2019_Z.csv", "\n".join([VIIRS_HDR, viirs_row(lat=42.0)]))
        zf.writestr("README.txt", "not a csv")
    p = load_points(cfg_for(tmp_path))
    assert len(p) == 4
    files = p["source_file"].astype(str).tolist()
    assert files == ["a/b/modis_2019_X.csv", "bundle.zip/viirs-snpp_2019_Y.csv",
                     "bundle.zip/viirs-snpp_2019_Y.csv", "bundle.zip/viirs-snpp_2019_Z.csv"]
    assert p["domain"].astype(str).tolist() == ["X", "Y", "Y", "Z"]


def test_cache_hit_and_invalidation_on_mtime(tmp_path, monkeypatch):
    write(tmp_path, "v.csv", VIIRS_HDR, [viirs_row(frp=2.0)])
    cfg = cfg_for(tmp_path)
    assert load_points(cfg)["frp"].tolist() == [2.0]
    assert len(list(cfg.cache_dir.glob("*.parquet"))) == 1

    real = ingest.read_input
    calls = []
    monkeypatch.setattr(ingest, "read_input", lambda *a, **k: calls.append(a) or real(*a, **k))
    assert load_points(cfg)["frp"].tolist() == [2.0]
    assert calls == []                                  # warm: served from parquet

    f = tmp_path / "v.csv"
    st = os.stat(f)
    f.write_text("\n".join([VIIRS_HDR, viirs_row(frp=3.0)]) + "\n")   # same size
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert load_points(cfg)["frp"].tolist() == [3.0]
    assert len(calls) == 1
    assert len(list(cfg.cache_dir.glob("*.parquet"))) == 1            # stale entry replaced


def test_cache_key_includes_confidence_thresholds(tmp_path):
    write(tmp_path, "m.csv", MODIS_HDR, [modis_row(conf=30)])
    assert load_points(cfg_for(tmp_path))["confidence_class"].tolist() == ["nominal"]
    assert load_points(cfg_for(tmp_path, modis_conf_low_max=30))["confidence_class"].tolist() == ["low"]
