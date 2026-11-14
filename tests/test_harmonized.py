import numpy as np
import pandas as pd
import pytest

from harmonize import harmonized as hmod
from harmonize.aggregate import cell_id_for
from harmonize.config import Config
from harmonize.coverage import build_coverage, tag_points
from harmonize.harmonized import HARMONIZED_COLUMNS, build_harmonized, write_harmonized

K = {"MODIS_ALL": 2.0, "MODIS_TERRA": 3.0, "MODIS_AQUA": 5.0}
CALLS = []


def stub_apply(coef, metric, rows, cfg, model):
    """y = k[source] * x; records the rows it was given."""
    CALLS.append(rows.copy())
    assert {"source", "daynight", metric, "frp_mean", "cell_lat", "period"} <= set(rows.columns)
    return rows["source"].map(K).to_numpy() * rows[metric].to_numpy("float64")


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(hmod, "_apply", stub_apply)


def coef(metric):
    return {"schema_version": 2, "recommended": {"metric": metric, "model": "stub"}}


def pts(rows, source_file):
    """rows: (source, lat, lon, 'YYYY-MM-DD HH:MM', daynight, frp)"""
    df = pd.DataFrame(rows, columns=["source", "latitude", "longitude", "dt", "daynight", "frp"])
    df["datetime_utc"] = pd.to_datetime(df["dt"], utc=True).astype("datetime64[ns, UTC]")
    df["acq_date"] = df["datetime_utc"].dt.strftime("%Y-%m-%d")
    df["scan"], df["bright_mir_k"] = 1.0, 320.0
    df["source_file"], df["domain"] = source_file, "G"
    return df.drop(columns="dt")


def tagged(*frames):
    cfg = Config()
    raw = pd.concat(frames, ignore_index=True)
    return tag_points(raw, build_coverage(raw, cfg), cfg)


def both(lat, lon, day, frp=10.0, dn="D"):
    return [("MODIS_TERRA", lat, lon, f"{day} 10:30", dn, frp), ("MODIS_AQUA", lat, lon, f"{day} 13:30", dn, frp)]


def scenario():
    """MODIS Dec 2011 - Feb 2012; VIIRS starts 2012-01-20 (same tile)."""
    m = pts([r for d in ("2011-12-01", "2011-12-15", "2012-01-02", "2012-01-10", "2012-01-25",
                         "2012-02-10", "2012-02-29") for r in both(38.3, 22.3, d)], "modis.csv")
    v = pts([("VIIRS_SNPP", 38.3, 22.3, f"{d} 11:00", "D", 1.0)
             for d in ("2012-01-20", "2012-01-25", "2012-01-26", "2012-02-10", "2012-02-29")],
            "viirs.csv")
    return tagged(m, v)


def test_mixed_month_viirs_plus_calibrated_modis_before_start():
    h = build_harmonized(scenario(), coef("n_hotspots"), Config())
    assert list(h.columns) == HARMONIZED_COLUMNS
    h = h[h["daynight"] == "ALL"].set_index("period")
    jan, dec, feb = h.loc["2012-01"], h.loc["2011-12"], h.loc["2012-02"]
    # Jan: VIIRS from the 20th (12 days), MODIS-only Jan 1-19
    assert jan["source_flag"] == "MIXED"
    assert (jan["viirs_days"], jan["modis_only_days"]) == (12, 19)
    assert jan["viirs_raw"] == 3 and jan["modis_raw"] == 6
    # harmonized = VIIRS + k_ALL * MODIS points before Jan 20 (4 points)
    assert jan["harmonized_value"] == pytest.approx(3 + 2.0 * 4)
    assert jan["modis_as_viirs_equivalent"] == pytest.approx(2.0 * 6)
    # Dec: no VIIRS at all
    assert dec["source_flag"] == "MODIS_CALIBRATED" and np.isnan(dec["viirs_raw"])
    assert dec["harmonized_value"] == pytest.approx(2.0 * 4) and dec["viirs_days"] == 0
    # Feb: fully VIIRS covered
    assert feb["source_flag"] == "VIIRS" and feb["harmonized_value"] == 2
    assert (feb["viirs_days"], feb["modis_only_days"]) == (29, 0)
    assert jan["cell_id"] == cell_id_for(38.3, 22.3, 0.25) and jan["metric"] == "n_hotspots"


def test_per_config_dispatch_terra_only_days():
    # Aqua's first data 2002-07-04 -> Jul 1-3 Terra-only; no VIIRS anywhere
    m = pts([("MODIS_TERRA", 40.3, 10.3, "2002-07-01 10:30", "D", 1.0),
             ("MODIS_TERRA", 40.3, 10.3, "2002-07-02 10:30", "D", 1.0),
             ("MODIS_AQUA", 40.3, 10.3, "2002-07-04 13:30", "D", 1.0),
             ("MODIS_TERRA", 40.3, 10.3, "2002-07-10 10:30", "D", 1.0),
             *both(40.3, 10.3, "2002-07-31")], "modis.csv")
    t = tagged(m)
    assert t["modis_config"].astype(str).tolist()[:2] == ["MODIS_TERRA", "MODIS_TERRA"]
    h = build_harmonized(t, coef("n_hotspots"), Config())
    r = h[h["daynight"] == "ALL"].iloc[0]
    assert r["source_flag"] == "MODIS_CALIBRATED"
    # 2 Terra-only points * 3 + 4 points on MODIS_ALL days * 2
    assert r["harmonized_value"] == pytest.approx(2 * 3.0 + 4 * 2.0)
    assert r["modis_as_viirs_equivalent"] == pytest.approx(14.0)
    srcs = set(pd.concat(CALLS)["source"])
    assert srcs == {"MODIS_TERRA", "MODIS_ALL"}


def test_fire_cell_days_cap():
    m = pts([r for d in pd.date_range("2011-11-01", "2011-11-30").strftime("%Y-%m-%d")
             for r in both(38.3, 22.3, d)], "modis.csv")
    m2 = pts([r for d in ("2012-01-01", "2012-01-10", "2012-01-19", "2012-01-25", "2012-01-31")
              for r in both(38.3, 22.3, d)], "modis2.csv")
    v = pts([("VIIRS_SNPP", 38.3, 22.3, f"2012-01-{d} 11:00", "D", 1.0) for d in (20, 31)], "viirs.csv")
    h = build_harmonized(tagged(m, m2, v), coef("fire_cell_days"), Config())
    h = h[h["daynight"] == "ALL"].set_index("period")
    nov = h.loc["2011-11"]
    assert nov["modis_raw"] == 30
    assert nov["harmonized_value"] == 30 and nov["modis_as_viirs_equivalent"] == 30   # 2*30 capped
    jan = h.loc["2012-01"]
    # VIIRS 2 days + calibrated MODIS-only part (3 days * 2 = 6) -> 8 <= 19 modis-only days
    assert jan["source_flag"] == "MIXED"
    assert jan["harmonized_value"] == pytest.approx(2 + 6)
    assert jan["harmonized_value"] <= 31


def test_write_harmonized(tmp_path):
    h = build_harmonized(scenario(), coef("frp_sum"), Config())
    paths = write_harmonized(h, tmp_path)
    assert [p.name for p in paths] == ["harmonized.csv"]
    back = pd.read_csv(paths[0])
    assert len(back) == len(h)
