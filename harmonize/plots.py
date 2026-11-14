"""Diagnostic figures (owner: C). Writes PNGs into ``cfg.out_dir / "plots"``.

make_plots(paired_by_source, harmonized_df_or_None, coef_json_or_None, cfg) -> list[Path]

* map_ratio_and_k.png         (a) per-tile VIIRS/MODIS ratio (observed, in-sample) and the
                              recommended model's effective k = sum(pred)/sum(MODIS) on the
                              same tiles; lon/lat scatter, no basemap dependency.
* domain_bias_lodo.png        (b) per-domain-year bias of the annual total under
                              leave-one-domain-out: ratio_global vs the best other model.
* monthly_by_domain_lodo.png  (c) small multiples per domain: VIIRS vs raw MODIS vs
                              out-of-fold calibrated (leave-one-domain-out).
* scatter_modis_vs_viirs.png  (d) cell-period MODIS vs VIIRS density (log axes, +1).
* harmonized_series.png       global monthly harmonized series (only if harmonized given).

(b) and (c) read ``cfg.out_dir/validation/{summary,domain_scores,monthly_oof}.csv``
written by :func:`harmonize.validate.run_validation`; they are skipped if absent.
A MODIS-only back-cast run (no paired table) returns [].
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm  # noqa: E402

from .config import METRICS, MODIS_ALL, Config  # noqa: E402

# colorblind-safe categorical slots (validated set, fixed order) + neutral ink
C_BLUE, C_ORANGE, C_AQUA = "#2a78d6", "#eb6834", "#1baf7a"
C_GREY, C_INK, C_MUTED = "#8a8985", "#0b0b0b", "#52514e"
SEQ = LinearSegmentedColormap.from_list("seq_blue", ["#dce9f8", "#7fb0ea", "#2a78d6", "#123f7a"])

UNITS = {"n_hotspots": "detections", "fire_cell_days": "fire cell-days", "frp_sum": "MW"}
LABELS = {"n_hotspots": "Hotspot count", "fire_cell_days": "Fire cell-days", "frp_sum": "FRP sum"}
MAP_TILE_DEG = 2.0
MAP_MIN_MODIS = 20.0          # tiles with less MODIS signal than this are not mapped (ratio too noisy)

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 130, "font.size": 9.5, "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": C_MUTED, "axes.labelcolor": C_INK, "xtick.color": C_MUTED,
    "ytick.color": C_MUTED, "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
    "legend.frameon": False, "lines.linewidth": 2, "figure.facecolor": "white",
})


# ---------------------------------------------------------------- helpers
def _read_val(cfg: Config, name: str) -> pd.DataFrame | None:
    p = cfg.out_dir / "validation" / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    return df if not df.empty else None


def _recommended(coef_json: dict | None, cfg: Config) -> tuple[str, str]:
    """(metric, model): coef JSON recommendation, else rank 1 of my validation summary."""
    rec = (coef_json or {}).get("recommended") or {}
    if rec.get("metric") and rec.get("model"):
        return rec["metric"], rec["model"]
    s = _read_val(cfg, "summary")
    if s is not None:
        s = s[(s["modis_source"] == MODIS_ALL) & (s["daynight"] == "ALL") & (s["rank_overall"] == 1)]
        if not s.empty:
            return s.iloc[0]["metric"], s.iloc[0]["model"]
    return "n_hotspots", "ratio_global"


def _best_other(summary: pd.DataFrame | None, metric: str, src: str = MODIS_ALL) -> str | None:
    """Best model under leave-domain-out for a metric, excluding the two baselines."""
    if summary is None:
        return None
    s = summary[(summary["metric"] == metric) & (summary["modis_source"] == src)
                & (summary["daynight"] == "ALL")
                & ~summary["model"].isin(["raw_modis", "ratio_global"])]
    return None if s.empty else s.sort_values("rank_in_metric").iloc[0]["model"]


def _model_params(paired, metric, model, coef_json, cfg):
    """Params for (metric, model, MODIS_ALL, ALL): from coef JSON, else in-sample fit."""
    from .validate import get_backend
    for c in (coef_json or {}).get("coefficients", []):
        if (c.get("metric"), c.get("model"), c.get("modis_source"), c.get("daynight")) == (
                metric, model, MODIS_ALL, "ALL"):
            return c["params"], "coefficients JSON"
    names, fit, apply, _ = get_backend()
    if model not in names:
        return None, None
    d = paired[paired["daynight"] == "ALL"]
    return fit(model, d, metric, cfg), "in-sample fit"


def _apply(params, rows, metric):
    from .validate import get_backend
    _, _, apply, _ = get_backend()
    return np.asarray(apply(params, rows, metric), float)


def _save(fig, path):
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------- (a) maps
def plot_map(paired: pd.DataFrame, coef_json, cfg: Config, path: Path) -> Path | None:
    from .validate import modis_rows
    metric, model = _recommended(coef_json, cfg)
    d = paired[paired["daynight"] == "ALL"]
    x = np.nan_to_num(d[f"modis_{metric}"].to_numpy(float))
    y = d[f"viirs_{metric}"].to_numpy(float)
    ty = np.floor(d["cell_lat"].to_numpy(float) / MAP_TILE_DEG) * MAP_TILE_DEG + MAP_TILE_DEG / 2
    tx = np.floor(d["cell_lon"].to_numpy(float) / MAP_TILE_DEG) * MAP_TILE_DEG + MAP_TILE_DEG / 2
    t = pd.DataFrame({"lat": ty, "lon": tx, "x": x, "y": y})
    params, how = None, None
    try:
        params, how = _model_params(paired, metric, model, coef_json, cfg)
    except Exception:  # noqa: BLE001 - map of k is optional
        params = None
    t["p"] = 0.0
    if params is not None:
        pos = x > 0
        try:
            t.loc[pos, "p"] = _apply(params, modis_rows(d[pos], MODIS_ALL), metric)
        except Exception:  # noqa: BLE001
            params = None
    g = t.groupby(["lat", "lon"], as_index=False)[["x", "y", "p"]].sum()
    g = g[g["x"] >= MAP_MIN_MODIS]
    if g.empty:
        return None
    g["ratio"] = g["y"] / g["x"]
    g["k"] = g["p"] / g["x"]
    vals = g["ratio"].to_numpy()
    norm = LogNorm(vmin=max(np.nanpercentile(vals, 2), 0.1), vmax=np.nanpercentile(vals, 98))
    panels = [("ratio", f"Observed VIIRS / MODIS ratio ({LABELS[metric].lower()})")]
    if params is not None:
        panels.append(("k", f"Model k = predicted / MODIS: {model} ({how})"))
    lon_rng = g["lon"].max() - g["lon"].min() + MAP_TILE_DEG
    lat_rng = g["lat"].max() - g["lat"].min() + MAP_TILE_DEG
    w = 11.0
    h = max(2.5, min(5.5, w * lat_rng / max(lon_rng, 1))) * len(panels) + 0.8
    fig, axes = plt.subplots(len(panels), 1, figsize=(w, h), squeeze=False)
    ms = max(2.0, (72 * w * MAP_TILE_DEG / max(lon_rng, 1)) ** 2 * 0.55)
    for ax, (col, title) in zip(axes[:, 0], panels):
        sc = ax.scatter(g["lon"], g["lat"], c=g[col].clip(norm.vmin, norm.vmax), cmap=SEQ,
                        norm=norm, marker="s", s=ms, linewidths=0)
        ax.set_title(title, loc="left")
        ax.set_xlabel("Longitude [deg E]")
        ax.set_ylabel("Latitude [deg N]")
        ax.set_aspect("equal", adjustable="datalim")
        cb = fig.colorbar(sc, ax=ax, shrink=0.85, pad=0.01)
        cb.set_label("VIIRS-equivalent per MODIS unit [-] (log)")
    fig.suptitle(f"{MAP_TILE_DEG:g} deg tiles, MODIS Terra+Aqua, day+night; tiles with MODIS "
                 f"< {MAP_MIN_MODIS:g} {UNITS[metric]} omitted", x=0.01, ha="left",
                 fontsize=9, color=C_MUTED)
    fig.tight_layout()
    return _save(fig, path)


# ---------------------------------------------------------------- (b) per-domain bias bars
def plot_domain_bias(cfg: Config, path: Path) -> Path | None:
    ds, summ = _read_val(cfg, "domain_scores"), _read_val(cfg, "summary")
    if ds is None:
        return None
    ds = ds[(ds["scheme"] == "leave_domain_out") & (ds["modis_source"] == MODIS_ALL)
            & (ds["daynight"] == "ALL")]
    if ds.empty:
        return None
    metrics = [m for m in METRICS if m in set(ds["metric"])]
    labels = (ds[["domain", "year"]].drop_duplicates().sort_values(["domain", "year"])
              .astype(str).agg(" ".join, axis=1).tolist())
    ypos = np.arange(len(labels))
    fig, axes = plt.subplots(1, len(metrics), figsize=(3.9 * len(metrics), 0.24 * len(labels) + 1.8),
                             sharey=True, squeeze=False)
    for ax, metric in zip(axes[0], metrics):
        other = _best_other(summ, metric)
        pairs = [("ratio_global", C_BLUE)] + ([(other, C_ORANGE)] if other else [])
        bh = 0.8 / len(pairs)
        for i, (mod, col) in enumerate(pairs):
            s = ds[(ds["metric"] == metric) & (ds["model"] == mod)].copy()
            s["lab"] = s["domain"].astype(str) + " " + s["year"].astype(str)
            v = s.set_index("lab")["bias_pct"].reindex(labels).to_numpy()
            p90 = np.nanpercentile(np.abs(v), 90) if np.isfinite(v).any() else np.nan
            ax.barh(ypos + (i - (len(pairs) - 1) / 2) * bh, v, height=bh * 0.9, color=col,
                    label=f"{mod} (p90 |bias| {p90:.0f} %)")
        ax.axvline(0, color=C_INK, lw=0.8)
        ax.set_title(LABELS[metric])
        ax.set_xlabel("Bias of annual total [%]")
        ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.07 * 24 / max(len(labels), 8)))
        ax.grid(axis="y", visible=False)
    axes[0, 0].set_yticks(ypos)
    axes[0, 0].set_yticklabels(labels, fontsize=8)
    axes[0, 0].invert_yaxis()
    fig.suptitle("Leave-one-domain-out: each country predicted by a model fitted on the others "
                 "(back-cast mode, MODIS Terra+Aqua, day+night)", x=0.01, ha="left",
                 fontweight="bold", fontsize=10)
    fig.tight_layout()
    return _save(fig, path)


# ---------------------------------------------------------------- (c) monthly small multiples
def plot_domain_monthly(cfg: Config, coef_json, path: Path) -> Path | None:
    mo, summ = _read_val(cfg, "monthly_oof"), _read_val(cfg, "summary")
    if mo is None:
        return None
    metric, model = _recommended(coef_json, cfg)
    mo = mo[(mo["scheme"] == "leave_domain_out") & (mo["modis_source"] == MODIS_ALL)
            & (mo["daynight"] == "ALL") & (mo["metric"] == metric)]
    if model not in set(mo["model"]):
        model = _best_other(summ, metric) or "ratio_global"
    cal = mo[mo["model"] == model]
    if cal.empty:
        return None
    years = sorted(int(v) for v in cal["year"].unique())
    yi = {y: i for i, y in enumerate(years)}          # years side by side, no empty gap years
    cal = cal.assign(t=cal["year"].map(yi) * 13 + cal["month"])
    doms = sorted(cal["domain"].astype(str).unique())
    nc = min(4, len(doms))
    nr = int(np.ceil(len(doms) / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(3.6 * nc, 2.4 * nr + 0.9), squeeze=False)
    for ax, dom in zip(axes.ravel(), doms):
        s = cal[cal["domain"].astype(str) == dom].sort_values("t")
        for yr, sy in s.groupby("year"):        # one segment per year: no line across gaps
            first = yr == s["year"].min()
            ax.plot(sy["t"], sy["obs"], color=C_BLUE, lw=2, label="VIIRS observed" if first else None)
            ax.plot(sy["t"], sy["raw_modis"], color=C_GREY, lw=1.4, ls="--",
                    label="raw MODIS" if first else None)
            ax.plot(sy["t"], sy["pred"], color=C_ORANGE, lw=1.6, marker="o", ms=3,
                    label=f"{model} (out-of-fold)" if first else None)
        b = 100 * (s["pred"].sum() - s["obs"].sum()) / s["obs"].sum() if s["obs"].sum() > 0 else np.nan
        ax.set_title(f"{dom}  (bias {b:+.0f} %)", fontsize=9.5)
        ax.ticklabel_format(axis="y", style="sci", scilimits=(-3, 4))
        ax.set_xticks([yi[y] * 13 + 6.5 for y in years])
        ax.set_xticklabels([str(y) for y in years])
        ax.grid(axis="x", visible=False)
    for ax in axes.ravel()[len(doms):]:
        ax.set_visible(False)
    for ax in axes[:, 0]:
        ax.set_ylabel(f"Monthly total [{UNITS[metric]}]")
    h, lab = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, lab, loc="upper right", ncol=3, fontsize=8.5)
    fig.suptitle(f"{LABELS[metric]} per domain, leave-one-domain-out (back-cast mode)",
                 x=0.01, ha="left", fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return _save(fig, path)


# ---------------------------------------------------------------- (d) scatter
def plot_scatter(paired: pd.DataFrame, path: Path, source: str = MODIS_ALL) -> Path:
    d = paired[paired["daynight"] == "ALL"]
    fig, axes = plt.subplots(1, len(METRICS), figsize=(4.4 * len(METRICS), 4.2))
    for ax, metric in zip(axes, METRICS):
        x = np.nan_to_num(d[f"modis_{metric}"].to_numpy(float))
        y = np.nan_to_num(d[f"viirs_{metric}"].to_numpy(float))
        hb = ax.hexbin(x + 1, y + 1, xscale="log", yscale="log", bins="log", mincnt=1,
                       gridsize=55, cmap=SEQ, linewidths=0)
        hi = max(x.max(), y.max()) + 1
        xs = np.geomspace(1, hi, 100)
        ax.plot(xs, xs, color=C_MUTED, lw=1, ls=":", label="1:1 (no calibration)")
        k = y.sum() / x.sum() if x.sum() > 0 else np.nan
        ax.plot(xs, k * (xs - 1) + 1, color=C_ORANGE, lw=1.6,
                label=f"ratio of totals k = {k:.2f}")
        ax.set_xlabel(f"MODIS {LABELS[metric].lower()} + 1 [{UNITS[metric]}]")
        ax.set_ylabel(f"VIIRS {LABELS[metric].lower()} + 1 [{UNITS[metric]}]")
        ax.set_title(LABELS[metric])
        ax.legend(fontsize=7.5, loc="upper left")
        fig.colorbar(hb, ax=ax, pad=0.01).set_label("cell-periods per bin (log)")
    fig.suptitle(f"Cell-period MODIS ({source}) vs VIIRS, day+night, n = {len(d):,} "
                 "(includes VIIRS-only and MODIS-only cells)", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    return _save(fig, path)


# ---------------------------------------------------------------- harmonized series
def plot_harmonized(h: pd.DataFrame, path: Path) -> Path | None:
    if h is None or h.empty or "harmonized_value" not in h:
        return None
    h = h[h["daynight"] == "ALL"] if "daynight" in h else h
    metric = str(h["metric"].iloc[0]) if "metric" in h else "n_hotspots"
    g = h.assign(month=h["period"].astype(str).str[:7]).groupby("month")[
        [c for c in ("viirs_raw", "modis_raw", "harmonized_value") if c in h]].sum(min_count=1)
    if g.empty:
        return None
    t = pd.to_datetime(g.index + "-01")
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.plot(t, g["harmonized_value"], color=C_ORANGE, lw=2, label="harmonized (VIIRS-equivalent)")
    if "viirs_raw" in g:
        ax.plot(t, g["viirs_raw"], color=C_BLUE, lw=1.4, label="VIIRS raw")
    if "modis_raw" in g:
        ax.plot(t, g["modis_raw"], color=C_GREY, lw=1.2, ls="--", label="MODIS raw")
    ax.set_ylabel(f"Monthly total [{UNITS.get(metric, '')}]")
    ax.set_xlabel("Month")
    ax.set_title(f"Harmonized series, all cells summed ({LABELS.get(metric, metric)})", loc="left")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


# ---------------------------------------------------------------- entry point
def make_plots(paired_by_source: dict[str, pd.DataFrame], harmonized_df_or_None,
               coef_json_or_None, cfg: Config) -> list[Path]:
    out = cfg.out_dir / "plots"
    paired_by_source = {k: v for k, v in (paired_by_source or {}).items()
                        if v is not None and not v.empty}
    if not paired_by_source:  # MODIS-only back-cast run: no overlap to compare against
        return []
    out.mkdir(parents=True, exist_ok=True)
    src = MODIS_ALL if MODIS_ALL in paired_by_source else next(iter(paired_by_source))
    paired = paired_by_source[src]
    written = [
        plot_map(paired, coef_json_or_None, cfg, out / "map_ratio_and_k.png"),
        plot_domain_bias(cfg, out / "domain_bias_lodo.png"),
        plot_domain_monthly(cfg, coef_json_or_None, out / "monthly_by_domain_lodo.png"),
        plot_scatter(paired, out / "scatter_modis_vs_viirs.png", src),
        plot_harmonized(harmonized_df_or_None, out / "harmonized_series.png"),
    ]
    return [p for p in written if p is not None]


if __name__ == "__main__":  # python -m harmonize.plots paired.parquet [out_dir]
    import sys
    path = sys.argv[1]
    df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(
        path, dtype={"cell_id": str, "period": str})
    cfg = Config(out_dir=sys.argv[2] if len(sys.argv) > 2 else "outputs")
    for f in make_plots({s: d for s, d in df.groupby("modis_source", observed=True)}, None, None, cfg):
        print(f)
