"""Fold construction in harmonize.validate: test masks partition the rows and never leak
a held-out month (temporal) or cell (spatial) into the training set."""
import numpy as np
import pandas as pd
import pytest

from harmonize.config import Config
from harmonize.validate import SCHEMES, make_folds, run_validation, score


def _toy(n_cells=23, n_months=12, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_cells):
        lat = 36.0 + c * 0.5
        for m in range(1, n_months + 1):
            for dn in ("D", "N", "ALL"):
                x = rng.poisson(2)
                rows.append(dict(cell_id=f"{c}_0", cell_lat=lat, cell_lon=10.0,
                                 period=f"2025-{m:02d}", period_start=f"2025-{m:02d}-01",
                                 daynight=dn, modis_n_hotspots=x, modis_fire_cell_days=min(x, 3),
                                 modis_frp_sum=10.0 * x, viirs_n_hotspots=5 * x + rng.poisson(1),
                                 viirs_fire_cell_days=3 * min(x, 3), viirs_frp_sum=12.0 * x,
                                 modis_source="MODIS_ALL"))
    return pd.DataFrame(rows)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_folds_partition_rows(scheme):
    df = _toy()
    folds = make_folds(df, scheme)
    stacked = np.vstack([m for _, m in folds])
    assert (stacked.sum(axis=0) == 1).all(), "every row must be tested exactly once"


@pytest.mark.parametrize("scheme", SCHEMES)
def test_no_leakage(scheme):
    df = _toy()
    for _, test in make_folds(df, scheme):
        train = ~test
        if scheme.startswith("temporal"):
            assert not set(df.loc[test, "period"]) & set(df.loc[train, "period"])
        else:
            assert not set(df.loc[test, "cell_id"]) & set(df.loc[train, "cell_id"])


def test_spatial_kfold_is_deterministic():
    df = _toy()
    a = [m for _, m in make_folds(df, "spatial_kfold")]
    b = [m for _, m in make_folds(df.sample(frac=1, random_state=1).sort_index(), "spatial_kfold")]
    assert all((x == y).all() for x, y in zip(a, b))


def test_blocked_split_halves():
    df = _toy()
    (_, t1), (_, t2) = make_folds(df, "temporal_blocked")
    assert set(df.loc[t2, "period"]) == {f"2025-{m:02d}" for m in range(1, 7)}
    assert set(df.loc[t1, "period"]) == {f"2025-{m:02d}" for m in range(7, 13)}


def test_score_perfect_prediction():
    obs = np.array([1.0, 4.0, 0.0, 9.0])
    s = score(obs, obs, np.array(["a", "a", "b", "c"]), x=np.array([1, 1, 0, 2]))
    assert s["bias_pct"] == 0 and s["r2_log"] == 1 and s["r2_monthly"] == 1
    assert s["spearman_months"] == pytest.approx(1.0)


def test_run_validation_smoke(tmp_path):
    df = _toy(n_cells=10)
    res = run_validation({"MODIS_ALL": df}, Config(out_dir=tmp_path), models=["ratio"])
    assert (tmp_path / "validation" / "summary.csv").exists()
    sc = res["scores"]
    assert set(sc["model"]) == {"raw_modis", "ratio"}
    # the toy relation is roughly y = 5x for n_hotspots: ratio must beat no calibration
    s = sc[(sc.metric == "n_hotspots") & (sc.daynight == "ALL") & (sc.eval_mode == "backcast")]
    best = s.groupby("model")["bias_pct"].apply(lambda b: b.abs().max())
    assert best["ratio"] < 15 < best["raw_modis"]
