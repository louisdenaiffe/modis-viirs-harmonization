import numpy as np
import pandas as pd
import pytest

from harmonize.aggregate import (aggregate, cell_id_for, coverage_from_points, make_paired,
                                 period_for)
from harmonize.config import Config


def pts(rows):
    """rows: (source, lat, lon, 'YYYY-MM-DD HH:MM', daynight, frp)"""
    df = pd.DataFrame(rows, columns=["source", "latitude", "longitude", "dt", "daynight", "frp"])
    df["datetime_utc"] = pd.to_datetime(df["dt"], utc=True).astype("datetime64[ns, UTC]")
    df["acq_date"] = df["datetime_utc"].dt.strftime("%Y-%m-%d")
    df["sensor"] = df["source"].str.split("_").str[0]
    df["type"] = 0
    df["confidence_class"] = "nominal"
    return df.drop(columns="dt")


def row(agg, **kw):
    m = np.ones(len(agg), bool)
    for k, v in kw.items():
        m &= (agg[k] == v).to_numpy()
    sel = agg[m]
    assert len(sel) == 1, sel
    return sel.iloc[0]


def test_cell_id_and_centre_math():
    assert cell_id_for(0.0, 0.0, 0.25) == "360_720"
    assert cell_id_for(45.1, 10.3, 0.25) == "540_761"
    assert cell_id_for(-0.1, -0.1, 0.25) == "359_719"
    assert cell_id_for(-33.9, -70.6, 0.25) == "224_437"
    assert cell_id_for(-90.0, -180.0, 1.0) == "0_0"
    assert list(cell_id_for(np.array([-0.1, 45.1]), np.array([-0.1, 10.3]), 0.25)) == [
        "359_719", "540_761"]
    cfg = Config(cell_size_deg=0.25)
    agg = aggregate(pts([("VIIRS_SNPP", -33.9, -70.6, "2025-01-05 10:00", "D", 1.0)]), cfg)
    r = agg.iloc[0]
    assert r["cell_id"] == "224_437"
    assert r["cell_lat"] == pytest.approx(-90 + 224.5 * 0.25)  # -33.875
    assert r["cell_lon"] == pytest.approx(-180 + 437.5 * 0.25)  # -70.625


def test_period_for():
    s = pd.Series(pd.to_datetime(["2025-07-31 23:59", "2025-08-01 00:01"], utc=True))
    assert period_for(s, "month").tolist() == ["2025-07", "2025-08"]
    assert period_for(s, "day").tolist() == ["2025-07-31", "2025-08-01"]
    assert period_for(pd.Timestamp("2025-03-04 10:00", tz="UTC"), "month") == "2025-03"
    with pytest.raises(ValueError):
        period_for(s, "week")


def test_month_vs_day_periods():
    p = pts([("VIIRS_SNPP", 40.0, 10.0, "2025-07-01 01:00", "N", 1.0),
             ("VIIRS_SNPP", 40.0, 10.0, "2025-07-01 13:00", "D", 2.0),
             ("VIIRS_SNPP", 40.0, 10.0, "2025-07-15 13:00", "D", 4.0)])
    m = aggregate(p, Config(time_step="month"))
    r = row(m, daynight="ALL")
    assert (r["period"], r["period_start"], r["n_hotspots"], r["fire_cell_days"], r["frp_sum"]) == (
        "2025-07", "2025-07-01", 3, 2, 7.0)
    r = row(m, daynight="D")
    assert (r["n_hotspots"], r["fire_cell_days"]) == (2, 2)
    d = aggregate(p, Config(time_step="day"))
    assert sorted(d.loc[d.daynight == "ALL", "period"]) == ["2025-07-01", "2025-07-15"]
    assert (d["fire_cell_days"] == 1).all()
    assert (d["period"] == d["period_start"]).all()
    r = row(d, daynight="ALL", period="2025-07-01")
    assert r["n_hotspots"] == 2


def test_modis_all_is_union_and_daynight_all_is_union():
    p = pts([("MODIS_TERRA", 40.0, 10.0, "2025-07-03 10:30", "D", 5.0),
             ("MODIS_AQUA", 40.0, 10.0, "2025-07-03 13:30", "D", 7.0),
             ("MODIS_AQUA", 40.0, 10.0, "2025-07-03 01:30", "N", 1.0),
             ("MODIS_TERRA", 40.0, 10.0, "2025-07-09 21:30", "N", 2.0)])
    agg = aggregate(p, Config())
    assert set(agg["source"]) == {"MODIS_TERRA", "MODIS_AQUA", "MODIS_ALL"}
    # Terra and Aqua on the same day -> counts once in MODIS_ALL
    r = row(agg, source="MODIS_ALL", daynight="D")
    assert (r["n_hotspots"], r["fire_cell_days"], r["frp_sum"]) == (2, 1, 12.0)
    # ALL = D ∪ N: 07-03 (D and N) + 07-09 -> 2 days, not 1+2=3
    r = row(agg, source="MODIS_ALL", daynight="ALL")
    assert (r["n_hotspots"], r["fire_cell_days"], r["frp_sum"]) == (4, 2, 15.0)
    r = row(agg, source="MODIS_AQUA", daynight="ALL")
    assert (r["n_hotspots"], r["fire_cell_days"]) == (2, 1)
    assert (agg["n_hotspots"] > 0).all()
    assert agg["n_hotspots"].dtype == "int64" and agg["fire_cell_days"].dtype == "int64"


def test_make_paired_zero_fill_and_coverage():
    cfg = Config()
    raw = pts([
        ("MODIS_AQUA", 40.0, 10.0, "2025-07-03 13:30", "D", 7.0),   # both sensors, cell A
        ("VIIRS_SNPP", 40.0, 10.0, "2025-07-03 13:00", "D", 1.0),
        ("MODIS_TERRA", 41.0, 11.0, "2025-07-04 10:30", "D", 3.0),  # MODIS-only cell B
        ("VIIRS_SNPP", 42.0, 12.0, "2025-07-05 01:00", "N", 2.0),   # VIIRS-only cell C
        ("MODIS_AQUA", 40.0, 10.0, "2025-06-03 13:30", "D", 9.0),   # June: VIIRS absent
        ("VIIRS_SNPP", 40.0, 10.0, "2025-08-03 13:00", "D", 9.0),   # Aug: MODIS only filtered-out pt
        ("MODIS_AQUA", 43.0, 13.0, "2025-08-03 13:00", "D", 9.0),
    ])
    raw["type"] = [0, 0, 0, 0, 0, 0, 2]
    cov = coverage_from_points(raw, cfg)
    assert cov["MODIS_ALL"] == {"2025-06", "2025-07", "2025-08"}
    assert cov["VIIRS_SNPP"] == {"2025-07", "2025-08"}
    filt = raw[raw["type"] == 0]
    agg = aggregate(filt, cfg)
    paired = make_paired(agg, "MODIS_ALL", cfg, coverage=cov)
    assert list(paired.columns) == [
        "cell_id", "cell_lat", "cell_lon", "period", "period_start", "daynight",
        "modis_n_hotspots", "modis_fire_cell_days", "modis_frp_sum",
        "viirs_n_hotspots", "viirs_fire_cell_days", "viirs_frp_sum", "modis_source"]
    assert set(paired["period"]) == {"2025-07", "2025-08"}  # June dropped
    assert (paired["modis_source"] == "MODIS_ALL").all()
    a, b, c = cell_id_for(40.0, 10.0, 0.25), cell_id_for(41.0, 11.0, 0.25), cell_id_for(42.0, 12.0, 0.25)
    r = row(paired, cell_id=b, period="2025-07", daynight="D")
    assert (r["modis_n_hotspots"], r["viirs_n_hotspots"], r["viirs_frp_sum"]) == (1, 0, 0.0)
    r = row(paired, cell_id=c, period="2025-07", daynight="N")
    assert (r["modis_n_hotspots"], r["modis_fire_cell_days"], r["viirs_n_hotspots"]) == (0, 0, 1)
    assert r["cell_lat"] == pytest.approx(42.125)
    r = row(paired, cell_id=a, period="2025-07", daynight="ALL")
    assert (r["modis_n_hotspots"], r["viirs_n_hotspots"]) == (1, 1)
    # Aug is covered by MODIS via a filtered-out point -> VIIRS row kept with modis 0
    r = row(paired, cell_id=a, period="2025-08", daynight="D")
    assert (r["modis_n_hotspots"], r["viirs_n_hotspots"]) == (0, 1)
    assert paired["modis_n_hotspots"].dtype == "int64"
    assert not paired.isna().any().any()

    # Without coverage: inferred from agg (Aug has no MODIS rows after filtering) + warning
    with pytest.warns(UserWarning):
        p2 = make_paired(agg, "MODIS_ALL", cfg)
    assert set(p2["period"]) == {"2025-07"}
