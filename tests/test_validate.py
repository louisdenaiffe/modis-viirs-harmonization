"""harmonize.validate: folds partition the rows and never leak a held-out domain, year,
10-degree block or calendar month into the training set; OOF predictions really are
out-of-fold; scoring and the end-to-end run behave."""
import numpy as np
import pandas as pd
import pytest

from harmonize import validate as V
from harmonize.config import Config
from harmonize.validate import SCHEMES, make_folds, run_validation

DOMAINS = {"Alpha": (40.0, 10.0, 5.0), "Beta": (-15.0, -50.0, 3.0), "Gamma": (60.0, 100.0, 8.0)}


def _toy(years=(2019, 2023), n_cells=6, seed=0):
    """Three far-apart domains with different true VIIRS/MODIS ratios (5, 3, 8)."""
    rng = np.random.default_rng(seed)
    rows = []
    for dom, (lat0, lon0, k) in DOMAINS.items():
        for c in range(n_cells):
            lat, lon = lat0 + 3.1 * c, lon0 + 4.3 * c        # cells span several 10-deg blocks
            for y in years:
                for m in range(1, 13):
                    for dn in ("D", "N", "ALL"):
                        x = float(rng.poisson(4))
                        rows.append(dict(
                            cell_id=f"{dom}{c}", cell_lat=lat, cell_lon=lon, period=f"{y}-{m:02d}",
                            period_start=f"{y}-{m:02d}-01", daynight=dn, domain=dom,
                            modis_source="MODIS_ALL", year=y,
                            modis_n_hotspots=x, modis_fire_cell_days=min(x, 3.0),
                            modis_frp_sum=10.0 * x, modis_frp_mean=10.0 if x else np.nan,
                            modis_frp_p90=15.0 if x else np.nan, modis_scan_mean=1.5 if x else np.nan,
                            modis_bright_mir_mean=320.0 if x else np.nan,
                            modis_n_terra=x / 2 if x else np.nan, modis_n_aqua=x / 2 if x else np.nan,
                            viirs_n_hotspots=k * x, viirs_fire_cell_days=min(3 * x, 28.0),
                            viirs_frp_sum=8.0 * k * x, viirs_frp_mean=8.0, n_days_covered=28))
    return pd.DataFrame(rows)


def _group(df, scheme):
    if scheme == "leave_domain_out":
        return df["domain"].to_numpy()
    if scheme == "leave_year_out":
        return V.year_of(df)
    if scheme == "lomo":
        return V.month_of(df)
    return V.block_of(df)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_folds_partition_rows(scheme):
    df = _toy()
    folds = make_folds(df, scheme)
    assert len(folds) >= 2
    stacked = np.vstack([m for _, m in folds])
    assert (stacked.sum(axis=0) == 1).all(), "every row must be tested exactly once"


@pytest.mark.parametrize("scheme", SCHEMES)
def test_no_leakage(scheme):
    df = _toy()
    g = _group(df, scheme)
    for name, test in make_folds(df, scheme):
        assert not set(g[test]) & set(g[~test]), f"{scheme}/{name}: group in train and test"


def test_spatial_blocks_are_10deg_and_order_independent():
    df = _toy()
    shuffled = df.sample(frac=1, random_state=1)
    a = {n: set(df.loc[m, "cell_id"]) for n, m in make_folds(df, "spatial_block")}
    b = {n: set(shuffled.loc[m, "cell_id"]) for n, m in make_folds(shuffled, "spatial_block")}
    assert a == b
    # two cells in the same 10-degree block always share a fold
    blk = V.block_of(df)
    fold = np.empty(len(df), object)
    for n, m in make_folds(df, "spatial_block"):
        fold[m] = n
    assert pd.Series(fold).groupby(blk).nunique().max() == 1


def test_single_group_schemes_are_skipped():
    df = _toy(years=(2023,))
    assert make_folds(df, "leave_year_out") == []
    assert len(make_folds(df, "leave_domain_out")) == 3


def test_oof_never_sees_test_rows(monkeypatch, tmp_path):
    """A spy model records the training domains/years/months; each fold's training set must
    exclude the held-out group, and apply_model must never receive a VIIRS column."""
    seen = []

    def fit(name, paired, metric, cfg):
        seen.append(dict(domains=set(paired["domain"]), years=set(V.year_of(paired)),
                         months=set(V.month_of(paired)), blocks=set(V.block_of(paired))))
        return {"model": name, "k": float(paired[f"viirs_{metric}"].sum()
                                         / paired[f"modis_{metric}"].sum())}

    def apply(params, rows, metric):
        assert not [c for c in rows.columns if c.startswith("viirs_")]
        assert "source" in rows and metric in rows
        return params["k"] * rows[metric].to_numpy(float)

    monkeypatch.setattr(V, "get_backend", lambda: (["ratio_global"], fit, apply, "spy"))
    df = _toy()
    res = run_validation({"MODIS_ALL": df}, Config(out_dir=tmp_path), metrics=("n_hotspots",),
                         daynights=("ALL",), verbose=False)
    folds = res["folds"]
    assert len(seen) == len(folds)
    d_all = df[df.daynight == "ALL"].reset_index(drop=True)
    blocks_of_fold = {n: set(V.block_of(d_all[m])) for n, m in make_folds(d_all, "spatial_block")}
    for f, s in zip(folds.itertuples(), seen):
        if f.scheme == "leave_domain_out":
            assert f.fold not in s["domains"]
        elif f.scheme == "leave_year_out":
            assert int(f.fold) not in s["years"]
        elif f.scheme == "lomo":
            assert int(f.fold) not in s["months"]
        else:
            assert not blocks_of_fold[f.fold] & s["blocks"]


def test_leave_domain_out_measures_transfer(monkeypatch, tmp_path):
    """Domains have true ratios 5, 3, 8: a pooled ratio fitted without the held-out domain
    must be biased for it, while leave-one-month-out (domain seen in training) is not
    biased in total."""
    def fit(name, paired, metric, cfg):
        return {"k": float(paired[f"viirs_{metric}"].sum() / paired[f"modis_{metric}"].sum())}

    monkeypatch.setattr(V, "get_backend", lambda: (
        ["ratio_global"], fit, lambda p, r, m: p["k"] * r[m].to_numpy(float), "spy"))
    res = run_validation({"MODIS_ALL": _toy()}, Config(out_dir=tmp_path), metrics=("n_hotspots",),
                         daynights=("ALL",), verbose=False)
    sc = res["scores"].set_index(["scheme", "model"])
    assert sc.loc[("leave_domain_out", "ratio_global"), "p90_abs_bias_pct"] > 25
    assert abs(sc.loc[("lomo", "ratio_global"), "pooled_bias_pct"]) < 3
    # raw MODIS under-counts by 1 - 1/k for every domain
    assert sc.loc[("leave_domain_out", "raw_modis"), "max_abs_bias_pct"] == pytest.approx(
        100 * (1 - 1 / 8), abs=0.5)


def test_score_helpers():
    m = pd.DataFrame({"domain": "A", "year": 2020, "month": range(1, 13),
                      "obs": np.arange(1.0, 13.0), "pred": np.arange(1.0, 13.0) * 1.1})
    ds = V.score_domain_years(m)
    assert ds.loc[0, "bias_pct"] == pytest.approx(10.0)
    assert ds.loc[0, "spearman_monthly"] == pytest.approx(1.0)
    d = V.distribution(ds, m)
    assert d["p90_abs_bias_pct"] == pytest.approx(10.0) and d["n_domain_years"] == 1


def test_run_validation_stub_smoke(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "get_backend", lambda: (
        ["ratio_global", "ratio_regional"], V._stub_fit, V._stub_apply, "stub"))
    res = run_validation({"MODIS_ALL": _toy()}, Config(out_dir=tmp_path), verbose=False)
    for k in ("scores", "domain_scores", "monthly_oof", "folds", "summary"):
        assert (tmp_path / "validation" / f"{k}.csv").exists()
    s = res["summary"]
    assert set(s["model"]) == {"raw_modis", "ratio_global", "ratio_regional"}
    assert (s["scheme"] == "leave_domain_out").all()
    assert s.loc[s.model == "raw_modis", "rank_overall"].isna().all()
