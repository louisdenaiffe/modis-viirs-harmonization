"""Cross-test: fit on one set of paired tables, score on another (transfer to countries
never seen in training).

    python -m harmonize.crosstest --train runs/paired/A/all/paired.parquet \
        --test runs/paired/B/all/paired.parquet --out runs/crosstest/A_to_B --label A_to_B --jobs 16

Uses validate.py's model backend, back-cast evaluation mode (a model is applied only where
the MODIS metric is > 0 and compared with all VIIRS, VIIRS-only cells included) and its
per-domain-year scores, so the numbers read like the validation tables. One fit per
(modis_source, daynight, metric, model) on the whole training set, applied to the whole test
set. Nothing is subsampled. Writes ``scores.csv``, ``domain_scores.csv``,
``monthly_oof.csv`` and ``summary.csv`` (ranking by p90 |domain-year bias|).
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from . import validate as V
from .config import DAYNIGHT, METRICS, MODIS_CONFIGS, Config

_CTX: dict = {}


def _job(key):
    src, dn, m, mod = key
    c = _CTX
    tr, te = c["train"][(src, dn)], c["test"][(src, dn)]
    x = c["xs"][(src, dn)][m]
    idx = np.flatnonzero(x > 0)
    if mod == V.BASELINE_RAW:
        return key, idx, x[idx], None
    try:
        params = c["fit"](mod, tr, m, c["cfg"])
        p = np.asarray(c["apply"](params, c["rows"][(src, dn)].iloc[idx], m), float)
        if p.shape != (len(idx),):
            raise ValueError(f"apply_model returned shape {p.shape}")
        return key, idx, p, None
    except Exception as e:  # noqa: BLE001
        return key, idx, np.full(len(idx), np.nan), repr(e)


def cross_test(train_by_src: dict, test_by_src: dict, cfg: Config, label: str = "cross",
               models=None, metrics=METRICS, sources=MODIS_CONFIGS, daynights=DAYNIGHT,
               n_jobs: int | None = None, out_dir: Path | None = None,
               verbose: bool = True) -> dict[str, pd.DataFrame]:
    names, fit, apply, backend = V.get_backend()
    wanted = list(models) if models is not None else names
    model_list = [V.BASELINE_RAW, V.BASELINE_RATIO] + [m for m in wanted
                                                       if m not in (V.BASELINE_RAW, V.BASELINE_RATIO)]
    model_list = [m for m in model_list if m == V.BASELINE_RAW or m in names]
    n_jobs = V.resolve_jobs(n_jobs)
    log = print if verbose else (lambda *_: None)
    train, test, rows, xs, groups = {}, {}, {}, {}, {}
    for src in sources:
        a, b = train_by_src.get(src), test_by_src.get(src)
        if a is None or b is None or a.empty or b.empty:
            continue
        for dn in daynights:
            tr = a[a["daynight"].astype(str) == dn].reset_index(drop=True)
            te = b[b["daynight"].astype(str) == dn].reset_index(drop=True)
            if tr.empty or te.empty:
                continue
            train[(src, dn)], test[(src, dn)] = tr, te
            rows[(src, dn)] = V.modis_rows(te, src)
            xs[(src, dn)] = {m: np.nan_to_num(te[f"modis_{m}"].to_numpy(float)) for m in metrics}
            groups[(src, dn)] = V._group_codes(te)
    jobs = [(s, d, m, mod) for (s, d) in train for m in metrics for mod in model_list]
    log(f"cross-test {label}: backend={backend} {len(jobs)} fits, n_jobs={n_jobs}")
    _CTX.update(train=train, test=test, rows=rows, xs=xs, fit=fit, apply=apply, cfg=cfg)
    t0 = time.time()
    results = []
    try:
        if n_jobs <= 1:
            results = [_job(k) for k in jobs]
        else:
            # big tables first, so the long fits start early
            order = sorted(jobs, key=lambda k: -len(train[(k[0], k[1])]))
            with mp.get_context("fork").Pool(min(n_jobs, len(jobs))) as pool:
                results = list(pool.imap_unordered(_job, order))
    finally:
        _CTX.clear()
    log(f"  fits done in {time.time() - t0:.0f}s")
    monthly = []
    for (src, dn, m, mod), idx, p, err in results:
        if err:
            warnings.warn(f"{mod}/{m}/{src}/{dn} failed: {err}")
        codes, keys = groups[(src, dn)]
        ng = len(keys)
        pr = np.zeros(len(test[(src, dn)]))
        pr[idx] = p
        bad = np.bincount(codes, np.isnan(pr).astype(float), ng) > 0
        ps = np.bincount(codes, np.nan_to_num(pr), ng)
        ps[bad] = np.nan
        mt = keys.copy()
        mt["obs"] = np.bincount(codes, test[(src, dn)][f"viirs_{m}"].to_numpy(float), ng)
        mt["pred"] = ps
        mt["raw_modis"] = np.bincount(codes, xs[(src, dn)][m], ng)
        mt["scheme"], mt["metric"], mt["model"] = label, m, mod
        mt["modis_source"], mt["daynight"], mt["n_failed_folds"] = src, dn, int(err is not None)
        monthly.append(mt)
    mon = pd.concat(monthly, ignore_index=True) if monthly else pd.DataFrame()
    keys = ["scheme", "metric", "model", "modis_source", "daynight"]
    drows, srows = [], []
    for k, g in mon.groupby(keys, sort=False):
        ds = V.score_domain_years(g)
        tags = dict(zip(keys, k))
        drows.append(ds.assign(**tags))
        srows.append(dict(**tags, backend=backend, n_failed_folds=int(g["n_failed_folds"].max()),
                          **V.distribution(ds, g)))
    dscores = pd.concat(drows, ignore_index=True) if drows else pd.DataFrame()
    if not dscores.empty:
        dscores = dscores[keys + [c for c in dscores.columns if c not in keys]]
    scores = pd.DataFrame(srows)
    summary = scores.sort_values(["modis_source", "daynight", "p90_abs_bias_pct", "max_abs_bias_pct"]) \
        .reset_index(drop=True) if not scores.empty else scores
    res = {"scores": scores, "domain_scores": dscores, "monthly_oof": mon, "summary": summary}
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for k, v in res.items():
            v.to_csv(out_dir / f"{k}.csv", index=False)
    return res


def main(argv=None):
    from .pipeline import load_paired
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--train", type=Path, nargs="+", required=True)
    p.add_argument("--test", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--label", default="cross")
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument("--daynight", nargs="+", default=list(DAYNIGHT))
    p.add_argument("--sources", nargs="+", default=list(MODIS_CONFIGS))
    a = p.parse_args(argv)
    res = cross_test(load_paired(a.train), load_paired(a.test), Config(out_dir=a.out), a.label,
                     n_jobs=a.jobs, out_dir=a.out, sources=tuple(a.sources),
                     daynights=tuple(a.daynight))
    pd.set_option("display.width", 220)
    s = res["summary"]
    print(s[(s["daynight"] == "ALL")][["modis_source", "metric", "model", "median_abs_bias_pct",
                                       "p90_abs_bias_pct", "max_abs_bias_pct", "worst_domain_year",
                                       "pooled_bias_pct"]].round(1).to_string())


if __name__ == "__main__":
    main()
