"""End-to-end harmonization pipeline.

    python -m harmonize.pipeline [--data-dir data] [--out-dir outputs]
                                 [--cell-size 0.25] [--time-step month|day]
                                 [--keep-types 0] [--min-confidence nominal]
                                 [--coefficients path.json]   # apply existing coefficients, skip fitting

Reads every FIRMS CSV in data/, writes everything into outputs/.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, MODIS_ALL, SOURCES_MODIS
from . import ingest, aggregate as agg_mod, calibrate

log = logging.getLogger("harmonize")

KEYS = ["cell_id", "cell_lat", "cell_lon", "period", "daynight"]
MODIS_CANDIDATES = (MODIS_ALL, "MODIS_AQUA", "MODIS_TERRA")


def build_harmonized(agg: pd.DataFrame, coverage: dict, coef: dict, cfg: Config) -> pd.DataFrame:
    """SCHEMA §5: one row per (cell, period, daynight) over ALL periods (not just the overlap)."""
    rec = coef["recommended"]
    metric, model, msrc = rec["metric"], rec["model"], rec["modis_source"]
    vsrc = cfg.viirs_reference

    def side(src):
        d = agg.loc[agg["source"] == src, KEYS + [metric]]
        return d.rename(columns={metric: src})

    h = side(msrc).merge(side(vsrc), on=KEYS, how="outer")
    m_cov = h["period"].isin(coverage.get(msrc, set()))
    v_cov = h["period"].isin(coverage.get(vsrc, set()))
    # zero-fill inside covered periods, NaN outside
    h["modis_raw"] = np.where(m_cov, h[msrc].fillna(0), np.nan)
    h["viirs_raw"] = np.where(v_cov, h[vsrc].fillna(0), np.nan)

    eq = np.full(len(h), np.nan)
    for dn, idx in h.groupby("daynight").groups.items():
        x = h.loc[idx, "modis_raw"].to_numpy(dtype=float)
        ok = ~np.isnan(x)
        out = np.full(len(x), np.nan)
        if ok.any():
            out[ok] = calibrate.apply_coefficients(coef, metric, msrc, dn, x[ok], model=model,
                                                         fit_level=rec.get("fit_level"), cfg=cfg)
        eq[h.index.get_indexer(idx)] = out
    if metric == "fire_cell_days":  # a cell cannot burn on more days than the period has
        eq = np.minimum(eq, _period_days(h["period"], cfg.time_step))
    h["modis_as_viirs_equivalent"] = eq
    h["harmonized_value"] = np.where(v_cov, h["viirs_raw"], h["modis_as_viirs_equivalent"])
    h["source_flag"] = np.where(v_cov, "VIIRS", np.where(m_cov, "MODIS_CALIBRATED", "NONE"))
    h["metric"] = metric
    h = h[h["source_flag"] != "NONE"]
    cols = ["cell_id", "cell_lat", "cell_lon", "period", "daynight", "metric", "modis_raw",
            "viirs_raw", "modis_as_viirs_equivalent", "harmonized_value", "source_flag"]
    return h[cols].sort_values(["period", "daynight", "cell_id"]).reset_index(drop=True)


def choose_recommendation(calib_rec: dict, summary: pd.DataFrame) -> dict:
    """Final pick = best model in the independent hold-out summary (back-cast mode, pooled D+N,
    worst case over temporal AND spatial folds). The calibration module's own leave-one-month-out
    pick is kept for reference: it cannot see spatial transfer, which is what separates metrics."""
    s = summary[(summary["eval_mode"] == "backcast") & (summary["daynight"] == "ALL")
                & (summary["model"] != "raw_modis") & (summary["modis_source"] == MODIS_ALL)]
    if s.empty:
        return calib_rec
    best = s.sort_values(["rank_overall", "worst_abs_bias_pct"]).iloc[0]
    rec = {
        "metric": best["metric"], "model": best["model"], "modis_source": best["modis_source"],
        "fit_level": calib_rec.get("fit_level", "cell_period"), "use_daynight_split": False,
        "validation_worst_abs_bias_pct": float(best["worst_abs_bias_pct"]),
        "validation_min_r2_monthly": float(best["min_r2_monthly"]),
        "validation_min_spearman_months": float(best["min_spearman_months"]),
        "reason": ("Chosen on independent hold-out (leave-one-month-out, Jan-Jun/Jul-Dec, 5-fold cells, "
                   "north/south): lowest worst-case national bias with D+N pooled. Night-only ratios "
                   "are unstable; D/N split not used."),
        "calibration_module_pick": {k: calib_rec.get(k) for k in
                                    ("metric", "model", "modis_source", "lomo_wape_pct", "lomo_bias_pct")},
    }
    return rec


def _period_days(period: pd.Series, time_step: str) -> np.ndarray:
    if time_step == "day":
        return np.ones(len(period))
    return pd.PeriodIndex(period, freq="M").days_in_month.to_numpy(dtype=float)


def run(cfg: Config, coefficients_path: Path | None = None) -> dict:
    out = cfg.out_dir
    out.mkdir(parents=True, exist_ok=True)

    log.info("1/7 ingest %s", cfg.data_dir)
    pts_all = ingest.load_points(cfg)
    pts = ingest.apply_filters(pts_all, cfg)
    log.info("    %d raw points -> %d after filters", len(pts_all), len(pts))
    pts.to_csv(out / "hotspots_clean.csv", index=False)

    log.info("2/7 aggregate (%.3g deg, %s)", cfg.cell_size_deg, cfg.time_step)
    agg = agg_mod.aggregate(pts, cfg)
    agg.to_csv(out / "aggregated.csv", index=False)
    coverage = agg_mod.coverage_from_points(pts_all, cfg)

    vref = cfg.viirs_reference
    paired = {}
    for src in MODIS_CANDIDATES:
        if coverage.get(src) and coverage.get(vref) and coverage[src] & coverage[vref]:
            paired[src] = agg_mod.make_paired(agg, src, cfg, coverage=coverage)
    if paired:
        pd.concat(paired.values()).to_csv(out / "paired.csv", index=False)

    if coefficients_path:
        log.info("3/7 using existing coefficients %s", coefficients_path)
        coef = json.loads(Path(coefficients_path).read_text())
    else:
        if not paired:
            raise SystemExit("No MODIS/VIIRS overlap periods to calibrate on; pass --coefficients")
        log.info("3/7 calibrate")
        meta = {
            "source_files": sorted(pts_all["source_file"].unique().tolist()),
            "periods": sorted(set().union(*[set(p["period"]) for p in paired.values()])),
            "n_cells": int(agg["cell_id"].nunique()),
        }
        log.info("4/7 stability table (leave-one-month-out on national totals)")
        stab = calibrate.stability_table(paired, cfg)
        stab.to_csv(out / "calibration_stability.csv", index=False)
        coef = calibrate.fit_all(paired, cfg, training_meta=meta, stability=stab)
        coef["created_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    val = {}
    if paired:
        log.info("5/7 independent hold-out validation")
        from . import validate
        val = validate.run_validation(paired, cfg)
        if not coefficients_path:
            coef["recommended"] = choose_recommendation(coef["recommended"], val["summary"])
            (out / "calibration_coefficients.json").write_text(json.dumps(coef, indent=2))
            log.info("    recommended: %s", {k: coef["recommended"][k] for k in ("metric", "model", "modis_source")})

    log.info("6/7 harmonized.csv")
    harm = build_harmonized(agg, coverage, coef, cfg)
    harm.to_csv(out / "harmonized.csv", index=False)

    log.info("7/7 plots")
    from . import plots
    plots.make_plots(paired, harm, coef, cfg)
    log.info("done -> %s", out.resolve())
    return {"points": pts, "agg": agg, "paired": paired, "coef": coef, "validation": val,
            "harmonized": harm}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", default="outputs")
    p.add_argument("--cell-size", type=float, default=0.25)
    p.add_argument("--time-step", choices=["month", "day"], default="month")
    p.add_argument("--keep-types", type=int, nargs="+", default=[0])
    p.add_argument("--min-confidence", choices=["low", "nominal", "high"], default="nominal")
    p.add_argument("--coefficients", type=Path, default=None)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = Config(data_dir=a.data_dir, out_dir=a.out_dir, cell_size_deg=a.cell_size,
                 time_step=a.time_step, keep_types=tuple(a.keep_types), min_confidence=a.min_confidence)
    run(cfg, a.coefficients)


if __name__ == "__main__":
    main()
