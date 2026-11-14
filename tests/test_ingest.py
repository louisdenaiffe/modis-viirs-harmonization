import pandas as pd
import pytest

from harmonize.config import Config
from harmonize.ingest import POINT_COLUMNS, apply_filters, detect_sensor, load_points

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
    return Config(data_dir=tmp_path, out_dir=tmp_path / "out", **kw)


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
    assert p["bright_tir_k"].tolist() == [290.1, 290.0]


def test_missing_type_column_defaults_to_zero(tmp_path):
    hdr = VIIRS_HDR.rsplit(",", 1)[0]
    row = viirs_row().rsplit(",", 1)[0]
    write(tmp_path, "nrt.csv", hdr, [row])
    p = load_points(cfg_for(tmp_path))
    assert p["type"].tolist() == [0]


def test_filters_type_and_confidence_configurable(tmp_path):
    rows = [viirs_row(conf="l"), viirs_row(conf="n"), viirs_row(conf="h"),
            viirs_row(conf="h", typ=2), viirs_row(conf="n", typ=3)]
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
