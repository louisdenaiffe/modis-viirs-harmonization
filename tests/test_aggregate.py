import numpy as np
import pandas as pd
import pytest

from harmonize.aggregate import PAIRED_COLUMNS, aggregate, cell_id_for, make_paired, period_for
from harmonize.config import Config
from harmonize.coverage import build_coverage, tag_points


def pts(rows, source_file=None, domain=None, scan=1.0, mir=320.0):
    """rows: (source, lat, lon, 'YYYY-MM-DD HH:MM', daynight, frp)"""
    df = pd.DataFrame(rows, columns=["source", "latitude", "longitude", "dt", "daynight", "frp"])
    df["datetime_utc"] = pd.to_datetime(df["dt"], utc=True).astype("datetime64[ns, UTC]")
    df["acq_date"] = df["datetime_utc"].dt.strftime("%Y-%m-%d")
    df["sensor"] = df["source"].str.split("_").str[0]
    df["type"] = 0
    df["confidence_class"] = "nominal"
    df["scan"] = scan
    df["bright_mir_k"] = mir
    df["source_file"] = source_file if source_file is not None else df["sensor"] + ".csv"
    df["domain"] = domain if domain is not None else "D0"
    return df.drop(columns="dt")


def tagged(*frames, cfg=None):
    cfg = cfg or Config()
    raw = pd.concat(frames, ignore_index=True)
    return tag_points(raw, build_coverage(raw, cfg), cfg)


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


def test_features():
    p = pts([("MODIS_TERRA", 40.0, 10.0, "2025-07-03 10:30", "D", 10.0),
             ("MODIS_AQUA", 40.01, 10.0, "2025-07-03 13:30", "D", 20.0),
             ("MODIS_AQUA", 40.02, 10.0, "2025-07-04 13:30", "D", 30.0),
             ("MODIS_AQUA", 40.03, 10.0, "2025-07-05 01:30", "N", 40.0)])
    p["scan"] = [1.0, 2.0, 3.0, 4.0]
    p["bright_mir_k"] = [300.0, 310.0, 320.0, 330.0]
    p["domain"] = ["A", "B", "B", "A"]
    p.loc[3, "domain"] = "B"
    agg = aggregate(p, Config())
    r = row(agg, source="MODIS_ALL", daynight="ALL")
    assert r["frp_mean"] == pytest.approx(25.0)
    assert r["frp_p90"] == pytest.approx(np.percentile([10, 20, 30, 40], 90))
    assert r["scan_mean"] == pytest.approx(2.5)
    assert r["bright_mir_mean"] == pytest.approx(315.0)
    assert (r["n_terra"], r["n_aqua"], r["fire_cell_days"]) == (1, 3, 3)
    assert r["domain"] == "B"
    r = row(agg, source="MODIS_TERRA", daynight="D")
    assert (r["n_terra"], r["n_aqua"], r["frp_p90"]) == (1, 0, 10.0)
    r = row(agg, source="MODIS_AQUA", daynight="N")
    assert (r["n_hotspots"], r["frp_mean"], r["scan_mean"]) == (1, 40.0, 4.0)
    v = aggregate(pts([("VIIRS_SNPP", 40.0, 10.0, "2025-07-03 13:00", "D", 3.0)]), Config())
    assert (v["n_terra"] == 0).all() and (v["n_aqua"] == 0).all()
    assert set(v["source"]) == {"VIIRS_SNPP"}


def test_by_config_splits_terra_only_days():
    m = pts([("MODIS_TERRA", 40.5, 10.5, "2002-06-30 10:30", "D", 1.0),
             ("MODIS_TERRA", 40.5, 10.5, "2002-07-10 10:30", "D", 1.0),
             ("MODIS_AQUA", 40.5, 10.5, "2002-07-05 13:30", "D", 1.0),
             ("MODIS_AQUA", 40.5, 10.5, "2002-07-31 13:30", "D", 1.0),
             ("MODIS_TERRA", 40.5, 10.5, "2002-07-31 10:30", "N", 1.0)], source_file="m.csv")
    t = tagged(m)
    assert t["modis_config"].astype(str).tolist() == ["MODIS_TERRA", "MODIS_ALL", "MODIS_ALL",
                                                      "MODIS_ALL", "MODIS_ALL"]
    agg = aggregate(t, Config(), by_config=True)
    assert "modis_config" in agg.columns
    r = row(agg, source="MODIS_ALL", daynight="D", modis_config="MODIS_TERRA")
    assert (r["period"], r["n_hotspots"]) == ("2002-06", 1)
    r = row(agg, source="MODIS_ALL", daynight="D", modis_config="MODIS_ALL", period="2002-07")
    assert r["n_hotspots"] == 3


def test_paired_v1_bug_other_country_not_paired():
    """v1 failure 1: MODIS file of country X + VIIRS file of country Y on the same dates
    -> X's MODIS fires must NOT be paired with VIIRS = 0."""
    days = [f"2025-07-{d:02d} 10:30" for d in (1, 10, 20, 31)]
    mx = pts([(s, 45.3, 10.3, d, "D", 5.0) for d in days for s in ("MODIS_TERRA", "MODIS_AQUA")],
             source_file="modis_2025_X.csv", domain="X")
    vy = pts([("VIIRS_SNPP", 38.3, 22.3, d, "D", 1.0) for d in days],
             source_file="viirs-snpp_2025_Y.csv", domain="Y")
    # a third country Z where both sensors have files -> pairs normally
    mz = pts([(s, -10.3, 30.3, d, "D", 5.0) for d in days for s in ("MODIS_TERRA", "MODIS_AQUA")],
             source_file="modis_2025_Z.csv", domain="Z")
    vz = pts([("VIIRS_SNPP", -10.3, 30.3, d, "D", 1.0) for d in days],
             source_file="viirs-snpp_2025_Z.csv", domain="Z")
    t = tagged(mx, vy, mz, vz)
    x_cell, y_cell = cell_id_for(45.3, 10.3, 0.25), cell_id_for(38.3, 22.3, 0.25)
    for src in ("MODIS_ALL", "MODIS_TERRA", "MODIS_AQUA"):
        p = make_paired(t, src, Config())
        assert x_cell not in set(p["cell_id"]) and y_cell not in set(p["cell_id"])
        assert set(p["domain"]) == {"Z"}
        r = row(p, daynight="ALL")
        assert (r["modis_n_hotspots"], r["viirs_n_hotspots"]) == ((8 if src == "MODIS_ALL" else 4), 4)
        assert r["n_days_covered"] == 31


def test_paired_v1_bug_viirs_starts_mid_month():
    """v1 failure 2: VIIRS starts 2012-01-20 -> January MODIS before the 20th is excluded and
    n_days_covered = 12 (Jan 20..31)."""
    m = pts([(s, 38.3, 22.3, f"2012-{md} 10:30", "D", 10.0)
             for md in ("01-01", "01-05", "01-19", "01-20", "01-25", "02-10", "02-29")
             for s in ("MODIS_TERRA", "MODIS_AQUA")], source_file="modis_2012_G.csv")
    v = pts([("VIIRS_SNPP", 38.3, 22.3, f"2012-{md} 11:00", "D", 2.0)
             for md in ("01-20", "01-22", "02-10", "02-29")], source_file="viirs-snpp_2012_G.csv")
    p = make_paired(tagged(m, v), "MODIS_ALL", Config())
    jan, feb = row(p, period="2012-01", daynight="ALL"), row(p, period="2012-02", daynight="ALL")
    assert (jan["modis_n_hotspots"], jan["modis_fire_cell_days"], jan["viirs_n_hotspots"]) == (4, 2, 2)
    assert jan["n_days_covered"] == 12
    assert (feb["modis_fire_cell_days"], feb["viirs_fire_cell_days"], feb["n_days_covered"]) == (2, 2, 29)


def test_paired_terra_only_days_and_columns():
    # Aqua starts 07-04: Jul 1-3 are Terra-only; VIIRS covers all of July
    m = pts([("MODIS_TERRA", 40.3, 10.3, "2002-07-01 10:30", "D", 4.0),
             ("MODIS_TERRA", 40.3, 10.3, "2002-07-10 10:30", "D", 6.0),
             ("MODIS_AQUA", 40.3, 10.3, "2002-07-04 13:30", "D", 8.0),
             ("MODIS_TERRA", 40.3, 10.3, "2002-07-31 10:30", "N", 1.0),
             ("MODIS_AQUA", 40.3, 10.3, "2002-07-31 13:30", "N", 1.0)], source_file="m.csv")
    v = pts([("VIIRS_SNPP", 40.3, 10.3, "2002-07-01 11:00", "D", 1.0),
             ("VIIRS_SNPP", 40.4, 10.6, "2002-07-31 11:00", "N", 2.0)], source_file="v.csv")
    t = tagged(m, v)
    pa = make_paired(t, "MODIS_ALL", Config())
    pt = make_paired(t, "MODIS_TERRA", Config())
    assert list(pa.columns) == PAIRED_COLUMNS
    c = cell_id_for(40.3, 10.3, 0.25)
    r = row(pa, cell_id=c, daynight="D")
    assert (r["modis_n_hotspots"], r["viirs_n_hotspots"], r["n_days_covered"]) == (2, 0, 28)
    assert (r["modis_n_terra"], r["modis_n_aqua"], r["modis_frp_mean"]) == (1, 1, 7.0)
    assert np.isnan(r["viirs_frp_mean"])
    r = row(pt, cell_id=c, daynight="D")
    assert (r["modis_n_hotspots"], r["viirs_n_hotspots"], r["n_days_covered"]) == (2, 1, 31)
    # VIIRS-only cell: zero-filled counts, NaN MODIS features
    r = row(pa, cell_id=cell_id_for(40.4, 10.6, 0.25), daynight="N")
    assert (r["modis_n_hotspots"], r["modis_fire_cell_days"], r["modis_frp_sum"]) == (0, 0, 0.0)
    assert np.isnan(r["modis_frp_mean"]) and np.isnan(r["modis_n_terra"])
    assert r["viirs_frp_mean"] == 2.0 and r["cell_lat"] == pytest.approx(40.375)
    assert (pa["modis_source"] == "MODIS_ALL").all() and (pt["modis_source"] == "MODIS_TERRA").all()
    assert pa["modis_n_hotspots"].dtype == "int64" and pa["n_days_covered"].dtype == "int64"
    with pytest.raises(ValueError):
        make_paired(t, "VIIRS_SNPP", Config())


def test_paired_uses_explicit_coverage_without_attrs():
    m = pts([(s, 38.3, 22.3, "2012-01-25 10:30", "D", 1.0) for s in ("MODIS_TERRA", "MODIS_AQUA")]
            + [(s, 38.3, 22.3, d, "D", 1.0) for s in ("MODIS_TERRA", "MODIS_AQUA")
               for d in ("2012-01-01 10:30", "2012-01-31 10:30")])
    v = pts([("VIIRS_SNPP", 38.3, 22.3, d, "D", 1.0) for d in ("2012-01-20 11:00", "2012-01-31 11:00")])
    raw = pd.concat([m, v], ignore_index=True)
    cov = build_coverage(raw, Config())
    t = tag_points(raw, cov, Config())
    t.attrs = {}
    p = make_paired(t, "MODIS_ALL", Config(), coverage=cov)
    assert row(p, daynight="ALL")["n_days_covered"] == 12
    with pytest.warns(UserWarning):   # no coverage at all -> falls back to days with points
        p2 = make_paired(t, "MODIS_ALL", Config())
    assert row(p2, daynight="ALL")["n_days_covered"] == 3


def test_chunked_equals_unchunked(monkeypatch):
    import harmonize.aggregate as agg_mod
    import harmonize.coverage as cov_mod
    rng = np.random.default_rng(1)
    n = 3000
    src = rng.choice(["MODIS_TERRA", "MODIS_AQUA", "VIIRS_SNPP"], n)
    days = pd.to_datetime("2019-01-01") + pd.to_timedelta(rng.integers(0, 90, n), unit="D")
    p = pts(list(zip(src, rng.uniform(30, 50, n), rng.uniform(0, 20, n),
                     days.strftime("%Y-%m-%d 10:00"), rng.choice(["D", "N"], n),
                     rng.gamma(2.0, 10.0, n))))
    p["source_file"] = np.where(p["latitude"] > 40, "a.csv", "b.csv")
    full = tagged(p)
    a1, m1 = aggregate(full, Config()), make_paired(full, "MODIS_ALL", Config())
    monkeypatch.setattr(agg_mod, "CHUNK_ROWS", 200)
    monkeypatch.setattr(cov_mod, "_TAG_CHUNK", 333)
    small = tagged(p)
    pd.testing.assert_frame_equal(a1, aggregate(small, Config()))
    pd.testing.assert_frame_equal(m1, make_paired(small, "MODIS_ALL", Config()))
