"""End-to-end harmonization pipeline (global, multi-year).

    python -m harmonize.pipeline [--data-dir data] [--out-dir outputs]
                                 [--cell-size 0.25] [--time-step month|day]
                                 [--keep-types 0] [--min-confidence nominal]
                                 [--coefficients path.json]   # apply existing coefficients (back-cast)
                                 [--skip-validation]          # faster runs on very large inputs
                                 [--paired-only]              # stop after paired.parquet + coverage.parquet
                                 [--from-paired a.parquet b.parquet ...]  # calibrate + validate only
                                 [--jobs N]                   # parallel validation folds

Reads every FIRMS CSV / zip under --data-dir (any countries, any years, MODIS and/or VIIRS),
writes everything into --out-dir. See SCHEMA.md and METHOD.md.
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import Config, MODIS_CONFIGS
from . import ingest, coverage as cov_mod, aggregate as agg_mod, calibrate, harmonized as harm_mod

log = logging.getLogger("harmonize")


def choose_recommendation(calib_rec: dict, val: dict) -> dict:
    """Final pick from the INDEPENDENT validation (validate.py), Terra+Aqua, day+night pooled.

    1. Primary: p90 |domain-year bias| under leave-one-domain-out (transfer to unseen regions).
    2. Tie-break: among candidates within 1 point of the best, take the lowest p90 under
       leave-one-year-out. Once every region is in the calibration set (a global 2012-2024 fit),
       this is exactly the back-cast situation, so a model that equals the best on unseen regions
       but is better on seen regions in unseen years is the better product.
    The calibration module's own pick is kept under `calibration_module_pick`."""
    summary, scores = val.get("summary"), val.get("scores")
    if summary is None or summary.empty or "rank_overall" not in summary:
        return calib_rec
    s = summary.dropna(subset=["rank_overall"])
    for col, v in (("daynight", "ALL"), ("modis_source", "MODIS_ALL")):
        if col in s and (s[col] == v).any():
            s = s[s[col] == v]
    s = s[s["model"] != "raw_modis"]
    if s.empty:
        return calib_rec
    best_p90 = s["p90_abs_bias_pct"].min()
    tied = s[s["p90_abs_bias_pct"] <= best_p90 + 1.0].copy()
    tied["lyo_p90"] = float("nan")
    if scores is not None and "scheme" in scores and (scores["scheme"] == "leave_year_out").any():
        ly = scores[(scores["scheme"] == "leave_year_out") & (scores["modis_source"] == "MODIS_ALL")
                    & (scores["daynight"] == "ALL")].set_index(["metric", "model"])["p90_abs_bias_pct"]
        tied["lyo_p90"] = [ly.get((m, mo), float("nan")) for m, mo in zip(tied["metric"], tied["model"])]
    best = tied.sort_values(["lyo_p90", "p90_abs_bias_pct"], na_position="last").iloc[0]
    rec = {"metric": best["metric"], "model": best["model"],
           "reason": (f"Independent validation: p90 |domain-year bias| {best['p90_abs_bias_pct']:.1f}% under "
                      f"leave-one-domain-out (best {best_p90:.1f}%); tie-break on leave-one-year-out p90 "
                      f"({best['lyo_p90']:.1f}%). See validation/summary.csv and scores.csv."),
           "validation": {k: best[k] for k in best.index if k not in ("metric", "model")},
           "candidates_tied": tied[["metric", "model", "p90_abs_bias_pct", "lyo_p90"]].to_dict("records"),
           "calibration_module_pick": {k: calib_rec.get(k) for k in ("metric", "model", "reason")}}
    return json.loads(json.dumps(rec, default=str))


def _plain(df: pd.DataFrame) -> pd.DataFrame:
    """Shallow copy without .attrs (tag_points stores a non-serialisable CoverageIndex there)."""
    d = df.copy(deep=False)
    d.attrs = {}
    return d


def load_paired(paths) -> dict[str, pd.DataFrame]:
    """Concatenate paired tables written by ``--paired-only`` and split them by MODIS
    configuration. Valid as long as the inputs do not share (cell, period) keys, which holds
    for different years and, apart from border cells, for disjoint sets of countries
    (see METHOD.md, "Processing in parts")."""
    frames = [pd.read_parquet(p) for p in paths]
    frames = [f for f in frames if len(f)]
    if not frames:
        return {}
    for f in frames:   # categories differ between files; unify as plain strings first
        for c in ("domain", "modis_source", "daynight", "cell_id", "period", "period_start"):
            if c in f and isinstance(f[c].dtype, pd.CategoricalDtype):
                f[c] = f[c].astype(str)
    df = pd.concat(frames, ignore_index=True)
    del frames
    for c in ("domain", "modis_source", "daynight"):
        df[c] = df[c].astype("category")
    out = {}
    for src in MODIS_CONFIGS:
        g = df[df["modis_source"] == src].reset_index(drop=True)
        if len(g) and g["modis_n_hotspots"].sum() > 0 and g["viirs_n_hotspots"].sum() > 0:
            out[src] = g
    return out


def calibrate_and_validate(paired: dict, cfg: Config, meta: dict, skip_validation: bool = False,
                           n_jobs: int | None = None) -> tuple[dict, dict]:
    """Fit every model, run the independent validation and pick the recommendation."""
    log.info("4/8 calibrate")
    coef = calibrate.fit_all(paired, cfg, training_meta=meta)
    coef["created_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    val = {}
    if not skip_validation:
        log.info("5/8 independent hold-out validation")
        from . import validate
        val = validate.run_validation(paired, cfg, n_jobs=n_jobs)
        coef["recommended"] = choose_recommendation(coef["recommended"], val)
    (cfg.out_dir / "calibration_coefficients.json").write_text(json.dumps(coef, indent=2, default=str))
    log.info("    recommended: %s / %s", coef["recommended"]["metric"], coef["recommended"]["model"])
    return coef, val


def run_from_paired(cfg: Config, paired_paths, skip_validation: bool = False,
                    n_jobs: int | None = None, plots: bool = True) -> dict:
    """``--from-paired``: no ingestion. Load and concatenate paired tables, then calibrate
    and validate exactly as a single pass would."""
    out = cfg.out_dir
    out.mkdir(parents=True, exist_ok=True)
    paths = [Path(p) for p in paired_paths]
    log.info("1-3/8 loading %d paired tables", len(paths))
    paired = load_paired(paths)
    if not paired:
        raise SystemExit("The paired tables hold no jointly covered MODIS/VIIRS data.")
    log.info("    %s", {k: len(v) for k, v in paired.items()})
    periods = sorted(set().union(*[set(p["period"].astype(str)) for p in paired.values()]))
    meta = {"source_files": [str(p) for p in paths],
            "domains": sorted(set().union(*[set(p["domain"].astype(str)) for p in paired.values()])),
            "periods": periods, "years": sorted({p[:4] for p in periods})}
    coef, val = calibrate_and_validate(paired, cfg, meta, skip_validation, n_jobs)
    if plots:
        log.info("7/8 plots")
        from . import plots as plots_mod
        plots_mod.make_plots(paired, None, coef, cfg)
    log.info("8/8 done -> %s", out.resolve())
    return {"paired": paired, "coef": coef, "validation": val}


def run(cfg: Config, coefficients_path: Path | None = None, skip_validation: bool = False,
        paired_only: bool = False, n_jobs: int | None = None, plots: bool = True) -> dict:
    out = cfg.out_dir
    out.mkdir(parents=True, exist_ok=True)

    log.info("1/8 ingest %s", cfg.data_dir)
    pts_all = ingest.load_points(cfg)
    if pts_all.empty:
        raise SystemExit(f"No FIRMS CSV/zip files found under {cfg.data_dir}")
    files = sorted(map(str, pts_all["source_file"].unique()))
    log.info("    %d files, %d raw points", len(files), len(pts_all))

    log.info("2/8 coverage (%.3g deg tiles, daily)", cfg.coverage_tile_deg)
    coverage = cov_mod.build_coverage(pts_all, cfg)
    coverage.to_parquet(out / "coverage.parquet", index=False)
    pts = ingest.apply_filters(pts_all, cfg)
    del pts_all
    gc.collect()
    pts = cov_mod.tag_points(pts, coverage, cfg)
    log.info("    %d points after filters; per source: %s", len(pts),
             pts["source"].value_counts().to_dict())
    pts_path = out / "hotspots_clean.parquet"
    if not paired_only:
        _plain(pts).to_parquet(pts_path, index=False)  # also used to reload points after calibration
        if cfg.points_format in ("csv", "both"):
            _plain(pts).to_csv(out / "hotspots_clean.csv", index=False)

    log.info("3/8 paired tables (jointly covered tile-days only)")
    paired = {}
    for src in MODIS_CONFIGS:
        p = agg_mod.make_paired(pts, src, cfg, coverage=coverage)
        if len(p) and p["modis_n_hotspots"].sum() > 0 and p["viirs_n_hotspots"].sum() > 0:
            paired[src] = p
    if paired:
        _plain(pd.concat(paired.values(), ignore_index=True)).to_parquet(out / "paired.parquet", index=False)
    log.info("    %s", {k: len(v) for k, v in paired.items()})
    del pts  # free ~GBs during calibration/validation; reloaded for the harmonized table
    gc.collect()
    if paired_only:
        log.info("--paired-only: stop -> %s", out.resolve())
        return {"paired": paired, "coverage": coverage}

    if coefficients_path:
        log.info("4/8 using existing coefficients %s", coefficients_path)
        coef = json.loads(Path(coefficients_path).read_text())
        val = {}
        if paired and not skip_validation:
            log.info("5/8 independent hold-out validation")
            from . import validate
            val = validate.run_validation(paired, cfg, n_jobs=n_jobs)
    else:
        if not paired:
            raise SystemExit("No tile-days covered by both MODIS and VIIRS: nothing to calibrate on. "
                             "Pass --coefficients to apply an existing calibration.")
        periods = sorted(set().union(*[set(p["period"]) for p in paired.values()]))
        meta = {"source_files": files,
                "domains": sorted(set().union(*[set(p["domain"].astype(str)) for p in paired.values()])),
                "periods": periods, "years": sorted({p[:4] for p in periods})}
        coef, val = calibrate_and_validate(paired, cfg, meta, skip_validation, n_jobs)

    log.info("6/8 harmonized table")
    pts = cov_mod.tag_points(pd.read_parquet(pts_path), coverage, cfg)
    harm = harm_mod.build_harmonized(pts, coef, cfg, coverage=coverage)
    del pts
    if cfg.points_format == "csv":
        pts_path.unlink()
    harm_mod.write_harmonized(_plain(harm), out)
    log.info("    %d rows; flags %s", len(harm), harm["source_flag"].value_counts().to_dict())

    if plots:
        log.info("7/8 plots")
        from . import plots as plots_mod
        plots_mod.make_plots(paired, harm, coef, cfg)
    log.info("8/8 done -> %s", out.resolve())
    return {"paired": paired, "coef": coef, "validation": val, "harmonized": harm}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", default="outputs")
    p.add_argument("--cell-size", type=float, default=0.25)
    p.add_argument("--time-step", choices=["month", "day"], default="month")
    p.add_argument("--keep-types", type=int, nargs="+", default=[0])
    p.add_argument("--min-confidence", choices=["low", "nominal", "high"], default="nominal")
    p.add_argument("--points-format", choices=["parquet", "csv", "both"], default="parquet")
    p.add_argument("--coefficients", type=Path, default=None)
    p.add_argument("--skip-validation", action="store_true")
    p.add_argument("--paired-only", action="store_true",
                   help="ingest, coverage, filter, tag, pair; write paired.parquet + coverage.parquet; stop")
    p.add_argument("--from-paired", type=Path, nargs="+", default=None, metavar="PARQUET",
                   help="skip ingestion: calibrate + validate on these paired tables (concatenated)")
    p.add_argument("--jobs", type=int, default=None,
                   help="parallel validation folds (default env HARMONIZE_JOBS or 1; -1 = all CPUs)")
    p.add_argument("--no-plots", action="store_true")
    a = p.parse_args(argv)
    if a.paired_only and (a.from_paired or a.coefficients):
        p.error("--paired-only cannot be combined with --from-paired or --coefficients")
    if a.from_paired and a.coefficients:
        p.error("--from-paired fits new coefficients; to apply existing ones run on raw data with --coefficients")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = Config(data_dir=a.data_dir, out_dir=a.out_dir, cell_size_deg=a.cell_size,
                 time_step=a.time_step, keep_types=tuple(a.keep_types),
                 min_confidence=a.min_confidence, points_format=a.points_format)
    if a.from_paired:
        run_from_paired(cfg, a.from_paired, a.skip_validation, a.jobs, plots=not a.no_plots)
    else:
        run(cfg, a.coefficients, a.skip_validation, paired_only=a.paired_only, n_jobs=a.jobs,
            plots=not a.no_plots)


if __name__ == "__main__":
    main()
