"""Add the glm_cell model to an existing full-recalibration output without rerunning the
other models (they are deterministic and unchanged).

    python scripts/add_glm_cell.py validate  PA PB WORK --jobs 12   # hold-outs, glm_cell only
    python scripts/add_glm_cell.py crosstest PA PB WORK --jobs 4    # A->B and B->A
    python scripts/add_glm_cell.py coef      PA PB WORK             # fit on everything
    python scripts/add_glm_cell.py merge     WORK outputs_full      # merge into the committed tables

A full rerun (METHOD.md §10) gives the same tables: glm_cell is in calibrate.MODELS.
"""
import argparse
import gzip
import json
import shutil
import sys
import warnings
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harmonize import calibrate as cal, crosstest as X, validate as V  # noqa: E402
from harmonize.config import DAYNIGHT, METRICS, Config  # noqa: E402
from harmonize.pipeline import choose_recommendation, load_paired  # noqa: E402
from tiers import tiers  # noqa: E402

M = "glm_cell"


def _gz(src: Path, dst: Path):
    with open(src, "rb") as f, gzip.open(dst, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)


def merge(work: Path, of: Path):
    # validation
    new = {k: pd.read_csv(work / "validation" / f"{k}.csv") for k in ("scores", "domain_scores")}
    vd = of / "validation"
    sc = pd.concat([pd.read_csv(vd / "scores.csv").query("model != @M"), new["scores"].query("model == @M")],
                   ignore_index=True)
    ds = pd.concat([pd.read_csv(vd / "domain_scores.csv").query("model != @M"),
                    new["domain_scores"].query("model == @M")], ignore_index=True)
    sc.to_csv(vd / "scores.csv", index=False)
    summary = V.summarize(sc)
    summary.to_csv(vd / "summary.csv", index=False)
    ds.to_csv(vd / "domain_scores.csv", index=False)
    ds[ds["daynight"] == "ALL"].to_csv(vd / "domain_scores_daynight_ALL.csv.gz", index=False)
    ds[ds["daynight"] != "ALL"].to_csv(vd / "domain_scores_daynight_D_N.csv.gz", index=False)
    tiers(ds).to_csv(vd / "tiers.csv", index=False)
    mo = work / "validation" / "monthly_oof.csv"
    if (vd / "monthly_oof.csv").exists() and mo.exists():
        cols = pd.read_csv(vd / "monthly_oof.csv", nrows=0).columns
        pd.read_csv(mo).query("model == @M")[cols].to_csv(vd / "monthly_oof.csv", mode="a", header=False, index=False)
    # cross-test
    pooled = []
    for lab in ("A_to_B", "B_to_A"):
        cd = of / "crosstest" / lab
        s = pd.concat([pd.read_csv(cd / "scores.csv").query("model != @M"),
                       pd.read_csv(work / "crosstest" / lab / "scores.csv").query("model == @M")], ignore_index=True)
        s.to_csv(cd / "scores.csv", index=False)
        s.sort_values(["modis_source", "daynight", "p90_abs_bias_pct", "max_abs_bias_pct"]).to_csv(
            cd / "summary.csv", index=False)
        nd = pd.read_csv(work / "crosstest" / lab / "domain_scores.csv")
        d = pd.concat([pd.read_csv(cd / "domain_scores.csv").query("model != @M"), nd.query("model == @M")],
                      ignore_index=True)
        d.to_csv(cd / "domain_scores.csv", index=False)
        _gz(cd / "domain_scores.csv", cd / "domain_scores.csv.gz")
        tiers(d).to_csv(cd / "tiers.csv", index=False)
        pooled.append(nd[nd["model"].isin([M, "raw_modis"])].assign(scheme="cross_pooled"))
    pt = tiers(pd.concat(pooled, ignore_index=True)).query("model == @M")
    old = pd.read_csv(of / "crosstest" / "pooled_tiers.csv").query("model != @M")
    pd.concat([old, pt[old.columns]], ignore_index=True).to_csv(of / "crosstest" / "pooled_tiers.csv", index=False)
    # coefficients
    cj = of / "calibration_coefficients.json"
    coef = json.loads(cj.read_text())
    add = json.loads((work / "coef_glm_cell.json").read_text())
    coef["coefficients"] = [c for c in coef["coefficients"] if c["model"] != M] + add
    old_rec = coef["recommended"]
    rec = choose_recommendation(old_rec.get("calibration_module_pick", old_rec), {"summary": summary, "scores": sc, "domain_scores": ds})
    coef["recommended"] = rec
    cj.write_text(json.dumps(coef, indent=2, default=str))
    print("recommended:", rec["metric"], rec["model"], "(was", old_rec["metric"], old_rec["model"] + ")")
    print("by metric:", json.dumps(rec["by_metric"], indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd"), ap.add_argument("args", nargs="+")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    if a.cmd == "merge":
        return merge(Path(a.args[0]), Path(a.args[1]))
    pa, pb, work = Path(a.args[0]), Path(a.args[1]), Path(a.args[2])
    work.mkdir(parents=True, exist_ok=True)
    if a.cmd == "validate":
        V.run_validation(load_paired([pa, pb]), Config(out_dir=work), models=[M], n_jobs=a.jobs)
    elif a.cmd == "crosstest":
        A, B = load_paired([pa]), load_paired([pb])
        for lab, tr, te in (("A_to_B", A, B), ("B_to_A", B, A)):
            X.cross_test(tr, te, Config(out_dir=work), lab, models=[M], n_jobs=a.jobs,
                         out_dir=work / "crosstest" / lab)
    elif a.cmd == "coef":
        out = []
        for src, df in load_paired([pa, pb]).items():
            for metric in METRICS:
                P = cal._rows(df, metric, "modis_", with_y=True)
                for dn in [d for d in DAYNIGHT if (P["dn"] == d).any()]:
                    Pd = cal._subset(P, P["dn"] == dn)
                    if dn != "ALL" and int((Pd["x"] > 0).sum()) < Config().min_pairs_for_split_fit:
                        continue
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        prm = cal._fit_prepared(M, Pd, metric, Config(), {})
                    out.append({"metric": metric, "model": M, "modis_source": str(src), "daynight": dn,
                                "params": prm, "n_train": prm["n_train"]})
                    print(src, metric, dn, flush=True)
        (work / "coef_glm_cell.json").write_text(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
