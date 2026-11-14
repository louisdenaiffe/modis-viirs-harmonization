import json
import warnings

import numpy as np
import pandas as pd
import pytest

from harmonize import calibrate as C
from harmonize.config import Config, METRICS


rng = np.random.default_rng(0)


def _synthetic_paired(k=5.0, n_cells=300, months=6, seed=1, n_rows_n=None):
    """Paired table where VIIRS ~ Poisson(k * MODIS) plus VIIRS-only cells."""
    r = np.random.default_rng(seed)
    rows = []
    for m in range(1, months + 1):
        period = f"2025-{m:02d}"
        for dn in ("D", "N"):
            nc = n_cells if (dn == "D" or n_rows_n is None) else n_rows_n
            for c in range(nc):
                x = r.poisson(3.0)
                y = r.poisson(k * x) if x > 0 else r.poisson(0.5)
                if x == 0 and y == 0:
                    continue
                rows.append(dict(cell_id=f"{c}_{dn}", cell_lat=0.0, cell_lon=0.0,
                                 period=period, period_start=f"{period}-01", daynight=dn,
                                 modis_n_hotspots=x, modis_fire_cell_days=min(x, 3),
                                 modis_frp_sum=10.0 * x,
                                 viirs_n_hotspots=y, viirs_fire_cell_days=min(y, 3),
                                 viirs_frp_sum=3.0 * y, modis_source="MODIS_ALL"))
    df = pd.DataFrame(rows)
    num = [c for c in df.columns if c.startswith(("modis_n", "modis_f", "viirs_"))]
    allp = df.groupby(["cell_id", "period"], as_index=False)[num].sum()
    allp = allp.assign(daynight="ALL", cell_lat=0.0, cell_lon=0.0,
                       period_start=allp.period + "-01", modis_source="MODIS_ALL")
    return pd.concat([df, allp], ignore_index=True)


def test_ratio_recovers_k():
    x = rng.poisson(4, 2000).astype(float)
    y = rng.poisson(6.0 * x).astype(float)
    p = C.fit_model("ratio", x, y)
    assert p["model"] == "ratio"
    assert p["k"] == pytest.approx(6.0, rel=0.02)
    assert np.allclose(C.apply_model(p, [0, 1, 2]), [0, p["k"], 2 * p["k"]])


def test_loglog_recovers_a_b_and_smearing_unbiased_totals():
    x = rng.lognormal(2, 1, 5000)
    a, b, o = 0.7, 0.8, 1.0
    y = np.exp(a + b * np.log(x + o) + rng.normal(0, 0.5, x.size)) - o
    y = np.clip(y, 0, None)
    p = C.fit_model("loglog", x, y, offset=o)
    assert p["b"] == pytest.approx(b, abs=0.03)
    assert p["a"] == pytest.approx(a, abs=0.08)
    assert p["smearing"] > 1.0  # lognormal residuals -> exp(sigma^2/2) ~ 1.13
    pred = C.apply_model(p, x)
    assert pred.sum() == pytest.approx(y.sum(), rel=0.05)
    p_nos = dict(p, smearing=1.0)
    assert C.apply_model(p_nos, x).sum() < 0.95 * y.sum()


def test_poisson_and_powerlaw_recover_b():
    x = rng.poisson(5, 4000).astype(float) + 1
    y = rng.poisson(2.0 * x ** 1.2).astype(float)
    pl = C.fit_model("powerlaw_total", x, y)
    assert pl["b"] == pytest.approx(1.2, abs=0.03)
    assert pl["c"] == pytest.approx(2.0, rel=0.1)
    assert C.apply_model(pl, x).sum() == pytest.approx(y.sum(), rel=1e-6)
    po = C.fit_model("poisson", x, y)
    assert C.apply_model(po, x).sum() == pytest.approx(y.sum(), rel=1e-3)


def test_powerlaw_total_absorbs_viirs_only_mass():
    x = np.array([0, 0, 0, 1, 2, 3], float)
    y = np.array([1, 1, 2, 5, 10, 15], float)
    p = C.fit_model("powerlaw_total", x, y)
    pred = C.apply_model(p, x)
    assert pred[:3].sum() == 0
    assert pred.sum() == pytest.approx(y.sum())


@pytest.mark.parametrize("name", C.MODELS)
def test_apply_model_zeros_negatives_nans(name):
    x = rng.poisson(3, 500).astype(float)
    y = rng.poisson(4 * x + 0.3).astype(float)
    p = C.fit_model(name, x, y)
    out = C.apply_model(p, [0.0, -5.0, np.nan, 2.0])
    assert out.shape == (4,)
    assert np.isnan(out[2])
    assert np.all(out[[0, 1, 3]] >= 0)
    assert out[1] == out[0]                   # negative treated as zero
    assert C.apply_model(p, 3.0).shape == (1,)


@pytest.mark.parametrize("name", C.MODELS)
@pytest.mark.parametrize("x,y", [([], []), ([0, 0, 0], [1, 2, 0]), ([np.nan, -1], [1, 2]),
                                  ([1, 2, 3], [0, 0, 0]), ([2], [7])])
def test_fit_model_degenerate_input_does_not_raise(name, x, y):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = C.fit_model(name, x, y)
    json.dumps(p, allow_nan=False)
    out = C.apply_model(p, [0, 1, 5])
    assert out.shape == (3,)
    assert np.all(np.isnan(out) | (out >= 0))


def test_fit_model_unknown():
    with pytest.raises(ValueError):
        C.fit_model("nope", [1], [1])


def test_fit_all_json_roundtrip_and_apply(tmp_path):
    df = _synthetic_paired(k=5.0)
    cfg = Config()
    paired = {"MODIS_ALL": df}
    stab = C.stability_table(paired, cfg)
    assert {"lomo_wape_pct", "cv_k_monthly", "daynight", "fit_level"} <= set(stab.columns)
    assert C.DN_SPLIT in set(stab.daynight)
    j = C.fit_all(paired, cfg, training_meta={"source_files": ["a.csv"]}, stability=stab)
    s = json.dumps(j, allow_nan=False)
    j2 = json.loads(s)
    assert j2["schema_version"] == 1
    assert j2["training_data"]["periods"][0] == "2025-01"
    assert set(j2["recommended"]) >= {"metric", "model", "modis_source", "fit_level", "reason"}
    assert {c["metric"] for c in j2["coefficients"]} == set(METRICS)
    assert {c["model"] for c in j2["coefficients"]} == set(C.MODELS)
    e = next(c for c in j2["coefficients"] if c["metric"] == "n_hotspots"
             and c["model"] == "ratio" and c["daynight"] == "ALL"
             and c["fit_level"] == "cell_period")
    assert e["params"]["k"] == pytest.approx(5.0, rel=0.1)
    assert {"r2_log", "bias_pct"} <= set(e["fit_stats"])
    out = C.apply_coefficients(j2, "n_hotspots", "MODIS_ALL", "D", [0, 1, 2],
                               model="ratio", fit_level="cell_period")
    assert out[2] == pytest.approx(2 * e["params"]["k"], rel=0.2)


def test_dn_fallback_to_all():
    df = _synthetic_paired(k=4.0, n_rows_n=5)    # very few N pairs
    cfg = Config(min_pairs_for_split_fit=30)
    j = C.fit_all({"MODIS_ALL": df}, cfg)
    dns = {c["daynight"] for c in j["coefficients"]}
    assert "N" not in dns and "D" in dns and "ALL" in dns
    allk = C.apply_coefficients(j, "n_hotspots", "MODIS_ALL", "ALL", [1.0], model="ratio",
                                fit_level="cell_period")
    with pytest.warns(UserWarning, match="using ALL"):
        nk = C.apply_coefficients(j, "n_hotspots", "MODIS_ALL", "N", [1.0], model="ratio",
                                  fit_level="cell_period")
    assert nk == pytest.approx(allk)
    stab = C.stability_table({"MODIS_ALL": df}, cfg)
    assert stab.loc[stab.daynight == "N", "fallback_to_all"].all()


def test_apply_coefficients_config_mismatch_warns_and_missing_raises():
    df = _synthetic_paired(months=3)
    j = C.fit_all({"MODIS_ALL": df}, Config())
    with pytest.warns(UserWarning, match="cell_size_deg"):
        C.apply_coefficients(j, "n_hotspots", "MODIS_ALL", "ALL", [1.0],
                             cfg=Config(cell_size_deg=0.5))
    with pytest.raises(KeyError):
        C.apply_coefficients(j, "n_hotspots", "MODIS_AQUA", "ALL", [1.0])
