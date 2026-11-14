"""Tests for harmonize.calibrate (v2, SCHEMA §5)."""
import json
import warnings

import numpy as np
import pandas as pd
import pytest

from harmonize import calibrate as C
from harmonize.config import Config

METRIC = "n_hotspots"


def _paired(regions, n_cells=60, periods=("2020-01", "2020-02", "2020-03"), seed=0,
            daynights=("ALL",), source="MODIS_ALL"):
    """Synthetic §4 paired table. ``regions`` = [(domain, lat0, lon0, k)]: cells spread over a
    ~4-degree box at (lat0, lon0), MODIS ~ Poisson, VIIRS ~ Poisson(k * MODIS)."""
    rng = np.random.default_rng(seed)
    rows = []
    for dom, lat0, lon0, k in regions:
        lat = lat0 + rng.integers(0, 16, n_cells) * 0.25 + 0.125
        lon = lon0 + rng.integers(0, 16, n_cells) * 0.25 + 0.125
        for per in periods:
            for dn in daynights:
                m = rng.poisson(20, n_cells).astype(float)
                v = rng.poisson(k * m).astype(float)
                rows.append(pd.DataFrame({
                    "cell_id": [f"{a}_{b}" for a, b in zip(lat, lon)], "cell_lat": lat, "cell_lon": lon,
                    "period": per, "period_start": per + "-01", "daynight": dn, "domain": dom,
                    "modis_source": source,
                    "modis_n_hotspots": m, "viirs_n_hotspots": v,
                    "modis_fire_cell_days": np.minimum(np.ceil(m / 4), 28),
                    "viirs_fire_cell_days": np.minimum(np.ceil(v / 4), 28),
                    "modis_frp_sum": m * 30, "viirs_frp_sum": v * 10,
                    "modis_frp_mean": np.where(m > 0, 30.0, np.nan),
                    "modis_frp_p90": np.where(m > 0, 60.0, np.nan),
                    "modis_scan_mean": np.where(m > 0, 1.5, np.nan),
                    "modis_bright_mir_mean": np.where(m > 0, 320.0, np.nan),
                    "modis_n_terra": np.floor(m / 2), "modis_n_aqua": m - np.floor(m / 2),
                    "viirs_frp_mean": np.where(v > 0, 10.0, np.nan), "n_days_covered": 31,
                }))
    return pd.concat(rows, ignore_index=True)


def _modis_rows(paired):
    """§4 paired -> §3-shaped MODIS rows, *without* any VIIRS column."""
    out = paired[[c for c in paired.columns if not c.startswith("viirs_")]].copy()
    out = out.rename(columns={c: c[len("modis_"):] for c in out.columns
                              if c.startswith("modis_") and c != "modis_source"})
    out["source"] = out.pop("modis_source")
    return out


REGIONS = [("A", 0.5, 0.5, 1.5), ("B", 40.5, 40.5, 3.0), ("C", -39.5, -99.5, 5.0)]


def test_models_listed():
    assert set(C.MODELS) >= {"ratio_global", "ratio_regional", "glm_features", "glm_regional"}


def test_ratio_regional_recovers_known_regional_k():
    paired = _paired(REGIONS, n_cells=80)
    prm = C.fit_model("ratio_regional", paired, METRIC, Config())
    rows = _modis_rows(paired)
    pred = C.apply_model(prm, rows, METRIC)
    for dom, *_, k in REGIONS:
        m = (rows["domain"] == dom).to_numpy()
        k_hat = pred[m].sum() / rows.loc[m, METRIC].sum()
        assert k_hat == pytest.approx(k, rel=0.05)
    # ratio_global is in between and preserves the total
    g = C.fit_model("ratio_global", paired, METRIC)
    assert C.apply_model(g, rows, METRIC).sum() == pytest.approx(paired["viirs_n_hotspots"].sum(), rel=1e-9)


def test_glm_recovers_density_effect_and_preserves_totals():
    rng = np.random.default_rng(3)
    n = 4000
    m = rng.integers(1, 200, n).astype(float)
    k = 4.0 * m ** -0.3                     # saturation: denser cells -> smaller factor
    df = pd.DataFrame({"cell_lat": rng.uniform(-40, 40, n), "cell_lon": rng.uniform(-100, 100, n),
                       "period": "2021-06", "daynight": "ALL", "modis_n_hotspots": m,
                       "viirs_n_hotspots": rng.poisson(k * m).astype(float)})
    prm = C.fit_model("glm_features", df, METRIC, Config(), features=["ldens"])
    glm = prm["by_daynight"]["ALL"]["glm"]
    slope = glm["beta"][0] / glm["features"]["sd"][0]
    assert slope == pytest.approx(-0.3, abs=0.03)
    pred = C.apply_model(prm, _modis_rows(df.assign(modis_source="MODIS_ALL")), METRIC)
    assert pred.sum() == pytest.approx(df["viirs_n_hotspots"].sum(), rel=1e-6)


def test_shrinkage_pulls_sparse_tile_toward_parent():
    paired = _paired([("A", 0.5, 0.5, 2.0)], n_cells=200)
    # one sparse cell in a different 5-degree tile, same 10/20/40-degree parents, raw ratio 10
    sparse = paired.iloc[:1].copy()
    sparse[["cell_lat", "cell_lon"]] = [7.125, 7.125]
    sparse["modis_n_hotspots"], sparse["viirs_n_hotspots"] = 2.0, 20.0
    df = pd.concat([paired, sparse], ignore_index=True)
    prm = C.fit_model("ratio_regional", df, METRIC, Config(region_levels_deg=(40, 20, 10, 5)))
    lev5 = [lv for lv in prm["by_daynight"]["ALL"]["regional"]["levels"] if lv["deg"] == 5.0][0]
    k_sparse = lev5["k"][C._key_str(int(C._tile_key([7.125], [7.125], 5.0)[0]))]
    assert k_sparse < 5.0                              # far from its raw ratio of 10
    assert abs(k_sparse - 2.0) < abs(10.0 - k_sparse)  # closer to the parent's ~2
    # explicit prior weight: the formula (V + lam k_parent) / (M + lam)
    prm0 = C.fit_model("ratio_regional", df, METRIC, Config(region_levels_deg=(5,)), lam={"5.0": 0.0})
    k0 = prm0["by_daynight"]["ALL"]["regional"]["levels"][0]["k"]
    assert k0[C._key_str(int(C._tile_key([7.125], [7.125], 5.0)[0]))] == pytest.approx(10.0)


def test_unseen_region_falls_back_to_parent_then_global():
    paired = _paired(REGIONS, n_cells=80)
    prm = C.fit_model("ratio_regional", paired, METRIC, Config())
    g = prm["by_daynight"]["ALL"]["regional"]["global"]
    lev40 = prm["by_daynight"]["ALL"]["regional"]["levels"][0]
    far = pd.DataFrame({"cell_lat": [70.1], "cell_lon": [160.1], "period": ["2020-01"],
                        "daynight": ["ALL"], METRIC: [10.0]})
    assert C.apply_model(prm, far, METRIC)[0] == pytest.approx(10 * g)
    # same 10-degree block as region A's data (0.5-4.5 N, 0.5-4.5 E) but another 5-degree tile -> 40-deg k
    near = far.assign(cell_lat=[2.1], cell_lon=[8.1])
    k40 = lev40["k"][C._key_str(int(C._tile_key([2.1], [8.1], 40.0)[0]))]
    assert C.apply_model(prm, near, METRIC)[0] == pytest.approx(10 * k40)
    for name in C.MODELS:   # every model handles unseen regions with finite output
        p = C.fit_model(name, paired, METRIC)
        assert np.isfinite(C.apply_model(p, far, METRIC)).all()


def test_apply_never_needs_viirs_columns():
    paired = _paired(REGIONS)
    rows = _modis_rows(paired)
    assert not any(c.startswith("viirs") for c in rows.columns)
    poisoned = rows.assign(viirs_n_hotspots=1e9, viirs_fire_cell_days=1e9, viirs_frp_sum=1e9)
    for name in C.MODELS:
        prm = C.fit_model(name, paired, METRIC)
        a = C.apply_model(prm, rows, METRIC)
        assert a.shape == (len(rows),) and (a >= 0).all()
        np.testing.assert_array_equal(a, C.apply_model(prm, poisoned, METRIC))


def test_robust_to_degenerate_inputs():
    paired = _paired(REGIONS)
    empty = paired.iloc[:0]
    zeros = paired.assign(modis_n_hotspots=0.0)
    nans = paired.assign(modis_n_hotspots=np.nan)
    for name in C.MODELS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for bad in (empty, zeros, nans):
                prm = C.fit_model(name, bad, METRIC)
                json.dumps(prm)
                assert prm["degenerate"]
            prm = C.fit_model(name, paired, METRIC)
        assert C.apply_model(prm, _modis_rows(empty), METRIC).shape == (0,)
        r = _modis_rows(paired.iloc[:5]).assign(n_hotspots=[np.nan, 0, -3, 4, 5])
        out = C.apply_model(prm, r, METRIC)
        assert np.isfinite(out).all() and (out[:3] == 0).all() and (out[3:] > 0).all()
        # missing feature / position columns -> training means / global factor
        bare = pd.DataFrame({METRIC: [4.0, 5.0]})
        assert np.isfinite(C.apply_model(prm, bare, METRIC)).all()


def test_fire_cell_days_capped_at_days_in_period():
    paired = _paired(REGIONS)
    prm = C.fit_model("ratio_regional", paired, "fire_cell_days")
    rows = pd.DataFrame({"cell_lat": [2.1, 2.1], "cell_lon": [2.1, 2.1], "period": ["2021-02", "2021-03"],
                         "daynight": "ALL", "fire_cell_days": [27.0, 30.0]})
    out = C.apply_model(prm, rows, "fire_cell_days")
    assert out[0] == 28 and out[1] == 31


def _fit_all(paired):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return C.fit_all({"MODIS_ALL": paired}, Config(min_pairs_for_split_fit=10),
                         training_meta={"source_files": ["x.csv"]})


def test_fit_all_json_round_trip_and_recommendation():
    regions = REGIONS + [("D", 30.5, 60.5, 2.5)]
    paired = _paired(regions, n_cells=30, daynights=("D", "N", "ALL"))
    coef = _fit_all(paired)
    s = json.dumps(coef, allow_nan=False)
    back = json.loads(s)
    assert back["schema_version"] == 2
    assert back["recommended"]["model"] in C.MODELS and back["recommended"]["metric"] in C.METRICS
    assert {(c["metric"], c["model"], c["daynight"]) for c in back["coefficients"]} >= \
        {(m, n, d) for m in C.METRICS for n in C.MODELS for d in ("D", "N", "ALL")}
    rows = _modis_rows(paired)
    for metric in C.METRICS:
        for name in C.MODELS:
            a = C.apply_coefficients(coef, metric, rows, model=name)
            b = C.apply_coefficients(back, metric, rows, model=name)
            np.testing.assert_allclose(a, b)
            assert (a >= 0).all()


def test_config_and_daynight_fallbacks():
    paired = _paired(REGIONS, n_cells=30, daynights=("ALL",))
    coef = _fit_all(paired)
    rows = _modis_rows(paired)
    ref = C.apply_coefficients(coef, METRIC, rows, model="ratio_regional")
    # Terra-only rows: no MODIS_TERRA entry -> MODIS_ALL with a warning
    with pytest.warns(RuntimeWarning, match="MODIS_TERRA"):
        terra = C.apply_coefficients(coef, METRIC, rows.assign(source="MODIS_TERRA"), model="ratio_regional")
    np.testing.assert_allclose(terra, ref)
    # D rows with no D entry -> ALL, silently
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        d = C.apply_coefficients(coef, METRIC, rows.assign(daynight="D"), model="ratio_regional")
    np.testing.assert_allclose(d, ref)
    # model defaults to the recommended one
    rec = C.apply_coefficients(coef, coef["recommended"]["metric"], rows)
    assert np.isfinite(rec).all()


def test_stability_table_leave_one_domain_out():
    paired = _paired(REGIONS + [("D", 30.5, 60.5, 2.5)], n_cells=30)
    st = C.stability_table({"MODIS_ALL": paired}, Config(), metrics=[METRIC])
    assert set(st["domain"]) == {"A", "B", "C", "D"}
    assert set(st["model"]) == set(C.MODELS) | {"modis_raw"}
    raw = st[st["model"] == "modis_raw"]
    np.testing.assert_allclose(raw["pred_total"], raw["modis_total"])
    summ = C.summarize_stability(st)
    assert {"median_abs_bias", "p90_abs_bias"} <= set(summ.columns)


# --------------------------------------------------------------------------- glm_cell
def _cell_paired(seed=0, years=range(2012, 2020)):
    """One region; half of the cells have twice the VIIRS/MODIS ratio of the other half."""
    rng = np.random.default_rng(seed)
    iy, ix = np.meshgrid(np.arange(8), np.arange(8), indexing="ij")
    lat, lon = (10.125 + iy * 0.25).ravel(), (20.125 + ix * 0.25).ravel()
    k = np.where((iy + ix).ravel() % 2 == 0, 2.0, 4.0)
    rows = []
    for y in years:
        for mo in ("01", "02", "03"):
            m = rng.poisson(200, len(lat)).astype(float)
            v = rng.poisson(k * m).astype(float)
            rows.append(pd.DataFrame({
                "cell_lat": lat, "cell_lon": lon, "period": f"{y}-{mo}", "daynight": "ALL",
                "domain": "X", "modis_source": "MODIS_ALL", "k_true": k,
                "modis_n_hotspots": m, "viirs_n_hotspots": v,
                "modis_fire_cell_days": np.minimum(np.ceil(m / 40), 28),
                "viirs_fire_cell_days": np.minimum(np.ceil(v / 40), 28),
                "modis_frp_sum": m * 30, "viirs_frp_sum": v * 10, "modis_frp_mean": 30.0,
                "modis_scan_mean": 1.5, "modis_n_terra": np.floor(m / 2), "modis_n_aqua": m - np.floor(m / 2)}))
    return pd.concat(rows, ignore_index=True)


def test_glm_cell_learns_cell_factors_and_keeps_totals():
    p = _cell_paired()
    train, test = p[p["period"] < "2019"], p[p["period"] >= "2019"]
    rows = _modis_rows(test)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cell = C.fit_model("glm_cell", train, METRIC)
        reg = C.fit_model("glm_regional", train, METRIC)
    pc, pr = C.apply_model(cell, rows, METRIC), C.apply_model(reg, rows, METRIC)
    truth = (test["k_true"] * test["modis_n_hotspots"]).to_numpy()
    assert np.abs(pc - truth).sum() < 0.3 * np.abs(pr - truth).sum()     # per-cell error much lower
    assert abs(pc.sum() / test["viirs_n_hotspots"].sum() - 1) < 0.02     # total preserved
    back = json.loads(json.dumps(cell))                                  # exact JSON round trip
    assert np.array_equal(C.apply_model(back, rows, METRIC), pc)


def test_glm_cell_unseen_cell_falls_back_and_is_finite():
    p = _cell_paired()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cell = C.fit_model("glm_cell", p, METRIC)
        reg = C.fit_model("glm_regional", p, METRIC)
    far = _modis_rows(p.head(20)).assign(cell_lat=-30.125, cell_lon=100.125)   # unseen cell and tile
    a, b = C.apply_model(cell, far, METRIC), C.apply_model(reg, far, METRIC)
    assert np.isfinite(a).all() and np.allclose(a, b)
    zero = _modis_rows(p.head(5)).assign(n_hotspots=0.0)
    assert (C.apply_model(cell, zero, METRIC) == 0).all()


def test_glm_cell_not_eligible_for_overall_pick():
    from harmonize.pipeline import choose_recommendation
    keys = dict(modis_source="MODIS_ALL", daynight="ALL", rank_overall=1.0)
    summary = pd.DataFrame([
        dict(metric="n_hotspots", model="glm_cell", p90_abs_bias_pct=10.0, **keys),
        dict(metric="fire_cell_days", model="glm_cell", p90_abs_bias_pct=11.0, **keys),
        dict(metric="fire_cell_days", model="glm_regional", p90_abs_bias_pct=20.0, **keys),
        dict(metric="n_hotspots", model="glm_regional", p90_abs_bias_pct=25.0, **keys)])
    rec = choose_recommendation({"metric": "x", "model": "y", "reason": ""}, {"summary": summary, "scores": None})
    assert (rec["metric"], rec["model"]) == ("fire_cell_days", "glm_regional")
    assert rec["by_metric"]["n_hotspots"]["model"] == "glm_cell"
    assert rec["by_metric"]["fire_cell_days"]["model"] == "glm_regional"
