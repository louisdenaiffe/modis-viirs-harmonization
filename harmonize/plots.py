"""Diagnostic figures (owner: C). Writes PNGs into ``cfg.out_dir / "plots"``.

make_plots(paired_by_source, harmonized_df_or_None, coef_json_or_None, cfg) -> list[Path]

* scatter_modis_vs_viirs.png   cell-period MODIS vs VIIRS per metric (log axes, +1), with
                               fitted curves (from coef_json if given, else in-sample fits)
* monthly_before_after.png     national monthly totals: raw MODIS vs VIIRS (before) and
                               MODIS-as-VIIRS-equivalent vs VIIRS (after)
* monthly_ratio.png            monthly VIIRS/MODIS ratio by day/night and by Aqua vs Terra
* validation_oof_monthly.png   (if outputs/validation/monthly_oof.csv exists) out-of-fold
                               monthly totals, leave-one-month-out
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .config import METRICS, MODIS_ALL, Config  # noqa: E402

# colorblind-safe categorical slots (validated set, first three hues) + neutral ink
C_BLUE, C_ORANGE, C_AQUA = "#2a78d6", "#eb6834", "#1baf7a"
C_GREY, C_INK, C_MUTED = "#8a8985", "#0b0b0b", "#52514e"
MODEL_COLORS = [C_BLUE, C_ORANGE, C_AQUA, "#e87ba4", "#6250d6"]

UNITS = {"n_hotspots": "detections", "fire_cell_days": "fire cell-days", "frp_sum": "MW"}
LABELS = {"n_hotspots": "Hotspot count", "fire_cell_days": "Fire cell-days", "frp_sum": "FRP sum"}

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 130, "font.size": 9.5, "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": C_MUTED, "axes.labelcolor": C_INK, "xtick.color": C_MUTED,
    "ytick.color": C_MUTED, "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
    "legend.frameon": False, "lines.linewidth": 2, "figure.facecolor": "white",
})


# ---------------------------------------------------------------- model evaluation
def _eval_params(model: str, params: dict, x: np.ndarray) -> np.ndarray | None:
    """Evaluate schema §4 params (ratio / loglog) or defer to B's apply_model."""
    x = np.asarray(x, float)
    if model == "ratio" and "k" in params:
        return params["k"] * x
    if model == "loglog" and {"a", "b"} <= set(params):
        off, sm = params.get("offset", 1.0), params.get("smearing", 1.0)
        return np.maximum(0.0, sm * np.exp(params["a"]) * (x + off) ** params["b"] - off)
    try:
        from .calibrate import apply_model
        return np.asarray(apply_model({"model": model, **params}, x), float)
    except Exception:
        try:
            from .calibrate import apply_model
            return np.asarray(apply_model(params, x), float)
        except Exception:
            return None


def _curves(paired: pd.DataFrame, metric: str, coef_json: dict | None, source: str,
            daynight: str = "ALL") -> dict[str, tuple[str, dict]]:
    """{label: (model, params)} for the curves to draw."""
    out = {}
    if coef_json:
        for c in coef_json.get("coefficients", []):
            if ((c["metric"], c["modis_source"], c["daynight"]) == (metric, source, daynight)
                    and c.get("fit_level", "cell_period") == "cell_period"):
                out[c["model"]] = (c["model"], {"model": c["model"], **c["params"]})
        if out:
            return out
    from .validate import get_backend
    names, fit, _apply, _ = get_backend()
    d = paired[paired["daynight"] == daynight]
    for m in names:
        try:
            p = fit(m, d[f"modis_{metric}"].to_numpy(float), d[f"viirs_{metric}"].to_numpy(float))
            out[f"{m} (in-sample)"] = (m, p)
        except Exception:
            pass
    return out


def _predict(model: str, params: dict, x) -> np.ndarray | None:
    try:
        from .calibrate import apply_model
        return np.asarray(apply_model(params, x), float)
    except Exception:
        return _eval_params(model, params, x)


def _monthly(df: pd.DataFrame, cols: list[str], daynight: str = "ALL") -> pd.DataFrame:
    d = df[df["daynight"] == daynight].copy()
    d["month"] = d["period"].astype(str).str[:7]
    return d.groupby("month")[cols].sum().sort_index()


def _month_axis(ax, months):
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels([m[2:] if len(months) > 14 else m[5:] for m in months],
                       rotation=0 if len(months) <= 14 else 90)
    ax.set_xlabel("Month" if len(months) <= 14 else "Month (YY-MM)")


# ---------------------------------------------------------------- figures
def plot_scatter(paired: pd.DataFrame, coef_json, path: Path, source: str = MODIS_ALL):
    fig, axes = plt.subplots(1, len(METRICS), figsize=(4.2 * len(METRICS), 4.1))
    d = paired[paired["daynight"] == "ALL"]
    for ax, metric in zip(axes, METRICS):
        x, y = d[f"modis_{metric}"].to_numpy(float), d[f"viirs_{metric}"].to_numpy(float)
        ax.scatter(x + 1, y + 1, s=9, alpha=0.35, color=C_GREY, edgecolor="none",
                   label=f"cell-months (n={len(d)})")
        hi = max(x.max(), y.max()) + 1
        xs = np.geomspace(1, hi, 200)
        ax.plot(xs, xs, color=C_MUTED, lw=1, ls=":", label="1:1 (no calibration)")
        for (label, (model, params)), col in zip(_curves(paired, metric, coef_json, source).items(),
                                                 MODEL_COLORS):
            yp = _predict(model, params, xs - 1)
            if yp is not None:
                ax.plot(xs, yp + 1, color=col, label=label)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel(f"MODIS ({source}) {LABELS[metric].lower()} + 1\n[{UNITS[metric]}]")
        ax.set_ylabel(f"VIIRS {LABELS[metric].lower()} + 1 [{UNITS[metric]}]")
        ax.set_title(LABELS[metric])
        ax.legend(fontsize=7.5, loc="upper left", framealpha=0.85, frameon=True, edgecolor="none")
    fig.suptitle("Cell-period MODIS vs VIIRS (day+night, log axes)", x=0.01, ha="left",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(path); plt.close(fig)


def plot_before_after(paired: pd.DataFrame, harmonized, coef_json, path: Path,
                      source: str = MODIS_ALL):
    cols = [f"modis_{m}" for m in METRICS] + [f"viirs_{m}" for m in METRICS]
    mon = _monthly(paired, cols)
    months = list(mon.index)
    rec = (coef_json or {}).get("recommended", {})
    fig, axes = plt.subplots(2, len(METRICS), figsize=(4.4 * len(METRICS), 6.4), sharex=True)
    for j, metric in enumerate(METRICS):
        ax = axes[0, j]
        ax.plot(range(len(months)), mon[f"viirs_{metric}"], color=C_BLUE, marker="o", ms=4,
                label="VIIRS (observed)")
        ax.plot(range(len(months)), mon[f"modis_{metric}"], color=C_ORANGE, marker="s", ms=4,
                label=f"MODIS raw ({source})")
        ax.set_title(f"{LABELS[metric]}: before")
        ax.set_ylabel(f"National monthly total [{UNITS[metric]}]")
        ax.legend(fontsize=8)
        # after
        ax = axes[1, j]
        after, label = None, None
        if harmonized is not None and "metric" in harmonized and (harmonized["metric"] == metric).any():
            h = harmonized[(harmonized["metric"] == metric) & (harmonized["daynight"] == "ALL")].copy()
            h["month"] = h["period"].astype(str).str[:7]
            after = h.groupby("month")["modis_as_viirs_equivalent"].sum().reindex(months)
            label = "MODIS as VIIRS-equivalent (harmonized.csv)"
        else:
            curves = _curves(paired, metric, coef_json, source)
            if curves:
                pick = rec.get("model") if rec.get("model") in curves else None
                key = pick or ("loglog" if "loglog" in curves else next(iter(curves)))
                if key not in curves:
                    key = next(k for k in curves if k.startswith(key)) if any(
                        k.startswith(key) for k in curves) else next(iter(curves))
                model, params = curves[key]
                d = paired[paired["daynight"] == "ALL"].copy()
                d["month"] = d["period"].astype(str).str[:7]
                yp = _predict(model, params, d[f"modis_{metric}"].to_numpy(float))
                if yp is not None:
                    d["p"] = yp
                    after = d.groupby("month")["p"].sum().reindex(months)
                    label = f"MODIS as VIIRS-equivalent ({key})"
        ax.plot(range(len(months)), mon[f"viirs_{metric}"], color=C_BLUE, marker="o", ms=4,
                label="VIIRS (observed)")
        if after is not None:
            ax.plot(range(len(months)), after.to_numpy(), color=C_AQUA, marker="D", ms=4,
                    label=label)
        ax.set_title(f"{LABELS[metric]}: after calibration")
        ax.set_ylabel(f"National monthly total [{UNITS[metric]}]")
        ax.legend(fontsize=8)
        _month_axis(ax, months)
    fig.suptitle("National monthly series, before and after calibration (in-sample)",
                 x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(path); plt.close(fig)


def plot_ratio(paired_by_source: dict, path: Path):
    fig, axes = plt.subplots(len(METRICS), 2, figsize=(10, 3.0 * len(METRICS)), sharex=True)
    ref = paired_by_source.get(MODIS_ALL)
    months = sorted(ref["period"].astype(str).str[:7].unique()) if ref is not None else []
    for i, metric in enumerate(METRICS):
        cols = [f"modis_{metric}", f"viirs_{metric}"]
        ax = axes[i, 0]
        if ref is not None:
            for dn, col, mk, lab in (("ALL", C_INK, "o", "day+night"), ("D", C_ORANGE, "s", "day"),
                                     ("N", C_BLUE, "^", "night")):
                m = _monthly(ref, cols, dn).reindex(months)
                r = m[cols[1]] / m[cols[0]].where(m[cols[0]] > 0)
                ax.plot(range(len(months)), r, color=col, marker=mk, ms=4, label=lab,
                        lw=2.4 if dn == "ALL" else 1.6)
        ax.set_title(f"{LABELS[metric]}: by overpass (Terra+Aqua)")
        ax.set_ylabel("VIIRS / MODIS ratio [-]")
        ax.legend(fontsize=7.5, ncol=3, loc="best")
        ax = axes[i, 1]
        for src, col, mk, lab in ((MODIS_ALL, C_INK, "o", "Terra + Aqua"),
                                  ("MODIS_AQUA", C_AQUA, "s", "Aqua (13:30 / 01:30)"),
                                  ("MODIS_TERRA", C_ORANGE, "^", "Terra (10:30 / 22:30)")):
            if src not in paired_by_source:
                continue
            m = _monthly(paired_by_source[src], cols).reindex(months)
            r = m[cols[1]] / m[cols[0]].where(m[cols[0]] > 0)
            ax.plot(range(len(months)), r, color=col, marker=mk, ms=4, label=lab,
                    lw=2.4 if src == MODIS_ALL else 1.6)
        ax.set_title(f"{LABELS[metric]}: by platform (day+night)")
        ax.set_ylabel("VIIRS / MODIS ratio [-]")
        ax.legend(fontsize=7.5, ncol=3, loc="best")
    for ax in axes[-1]:
        _month_axis(ax, months)
    from matplotlib.ticker import FuncFormatter, LogLocator
    for ax in axes.ravel():
        ax.set_yscale("log")
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo, hi * 4)                      # headroom for the legend row
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
        ax.legend(fontsize=7.5, ncol=3, loc="upper left")
    fig.suptitle("Monthly national VIIRS / MODIS ratio (log scale; gap where MODIS = 0)",
                 x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(path); plt.close(fig)


def plot_validation(monthly_oof: pd.DataFrame, path: Path, scheme: str = "temporal_lomo"):
    d = monthly_oof[(monthly_oof["scheme"] == scheme) & (monthly_oof["modis_source"] == MODIS_ALL)
                    & (monthly_oof["daynight"] == "ALL")]
    if "eval_mode" in d:
        d = d[d["eval_mode"] == "backcast"]
    if d.empty:
        return False
    models = list(dict.fromkeys(d["model"]))
    fig, axes = plt.subplots(1, len(METRICS), figsize=(4.4 * len(METRICS), 3.8))
    colors = dict(zip([m for m in models if m != "raw_modis"], [C_ORANGE, C_AQUA, "#e87ba4", "#6250d6"]))
    for ax, metric in zip(axes, METRICS):
        dm = d[d["metric"] == metric]
        months = sorted(dm["period"].unique())
        obs = dm.groupby("period")["obs"].first().reindex(months)
        ax.plot(range(len(months)), obs, color=C_BLUE, marker="o", ms=4, label="VIIRS observed")
        for m in models:
            s = dm[dm["model"] == m].set_index("period")["pred"].reindex(months)
            if m == "raw_modis":
                ax.plot(range(len(months)), s, color=C_GREY, ls="--", lw=1.4, label="raw MODIS")
            elif m in colors:
                ax.plot(range(len(months)), s, color=colors[m], marker="s", ms=3.5, lw=1.6,
                        label=f"{m} (held-out)")
        ax.set_title(LABELS[metric])
        ax.set_ylabel(f"National monthly total [{UNITS[metric]}]")
        _month_axis(ax, months)
        ax.legend(fontsize=8)
    fig.suptitle("Out-of-fold predictions, leave-one-month-out (each month predicted by a model "
                 "fitted on the other months; back-cast mode)", x=0.01, ha="left", fontweight="bold", fontsize=10)
    fig.tight_layout()
    fig.savefig(path); plt.close(fig)
    return True


def make_plots(paired_by_source: dict[str, pd.DataFrame], harmonized_df_or_None,
               coef_json_or_None, cfg: Config) -> list[Path]:
    out = cfg.out_dir / "plots"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    if not paired_by_source:  # e.g. a MODIS-only back-cast run: no overlap to compare against
        return written
    src = MODIS_ALL if MODIS_ALL in paired_by_source else next(iter(paired_by_source))
    paired = paired_by_source[src]
    p = out / "scatter_modis_vs_viirs.png"; plot_scatter(paired, coef_json_or_None, p, src); written.append(p)
    p = out / "monthly_before_after.png"
    plot_before_after(paired, harmonized_df_or_None, coef_json_or_None, p, src); written.append(p)
    p = out / "monthly_ratio.png"; plot_ratio(paired_by_source, p); written.append(p)
    vpath = cfg.out_dir / "validation" / "monthly_oof.csv"
    if vpath.exists():
        p = out / "validation_oof_monthly.png"
        if plot_validation(pd.read_csv(vpath, dtype={"period": str}), p):
            written.append(p)
    return written


if __name__ == "__main__":  # python -m harmonize.plots paired.csv [out_dir]
    import sys
    df = pd.read_csv(sys.argv[1], dtype={"cell_id": str, "period": str})
    cfg = Config(out_dir=sys.argv[2] if len(sys.argv) > 2 else "outputs")
    for f in make_plots({s: d for s, d in df.groupby("modis_source")}, None, None, cfg):
        print(f)
