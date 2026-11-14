"""Figures for the full recalibration: drift ratios and cross-test vs validation p90 by tier.

    python scripts/plot_full.py outputs_full
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harmonize.plots import C_BLUE, C_ORANGE, C_AQUA, C_INK, C_MUTED, C_GREY  # noqa: E402

plt.rcParams.update({"font.size": 9, "axes.edgecolor": C_GREY, "axes.labelcolor": C_MUTED,
                     "xtick.color": C_MUTED, "ytick.color": C_MUTED, "axes.grid": True,
                     "grid.color": "#e4e3df", "grid.linewidth": 0.6, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb"})
SRC = [("MODIS_ALL", "Terra+Aqua", C_BLUE), ("MODIS_TERRA", "Terra", C_ORANGE),
       ("MODIS_AQUA", "Aqua", C_AQUA)]
LAB = {"n_hotspots": "Hotspot count", "fire_cell_days": "Fire cell-days", "frp_sum": "FRP sum"}


def drift(root):
    r = pd.read_csv(root / "drift" / "drift_ratio.csv")
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4), sharey=True)
    for ax, m in zip(axes, LAB):
        ends = []
        for src, name, col in SRC:
            g = r[(r.metric == m) & (r.modis_source == src)].sort_values("year")
            base = g[g.year <= 2019]["ratio_median_country"].mean()
            y = g["ratio_median_country"] / base
            ax.plot(g.year, y, color=col, lw=2, marker="o", ms=4, label=name)
            ends.append([y.iloc[-1], name])
        ends.sort()
        for i in range(1, len(ends)):          # keep end labels >= 0.022 apart
            ends[i][0] = max(ends[i][0], ends[i - 1][0] + 0.022)
        for yv, name in ends:
            ax.annotate(name, (2024.3, yv), va="center", color=C_INK, fontsize=8,
                        annotation_clip=False)
        ax.axhline(1, color=C_GREY, lw=0.8)
        ax.axvspan(2019.5, 2024.5, color="#f0efec", zorder=0)
        ax.set_title(LAB[m], color=C_INK, loc="left", fontsize=10)
        ax.set_xlim(2011.5, 2026.3)
        ax.set_xticks([2012, 2016, 2020, 2024])
    axes[0].set_ylabel("VIIRS / MODIS ratio\n(index, 2012-2019 mean = 1)")
    axes[0].legend(frameon=False, loc="upper left", fontsize=8)
    fig.suptitle("Yearly VIIRS/MODIS ratio, median over countries (shaded: after 2019, orbit drift)",
                 x=0.01, ha="left", color=C_INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(root / "plots" / "drift_ratio.png", dpi=150)


if __name__ == "__main__":
    drift(Path(sys.argv[1]))


def bias_vs_size(root):
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tiers import size_table
    ds = pd.read_csv(root / "validation" / "domain_scores.csv")
    ds = ds[(ds.daynight == "ALL") & (ds.modis_source == "MODIS_ALL") & (ds.scheme == "domain_kfold")]
    d = ds.merge(size_table(ds), on=["scheme", "modis_source", "daynight", "domain", "year"])
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, m in zip(axes, ["fire_cell_days", "frp_sum"]):
        g = d[(d.metric == m) & (d.model == "glm_regional")].dropna(subset=["bias_pct"])
        ax.scatter(g.viirs_detections.clip(lower=1), g.bias_pct.abs().clip(lower=0.1), s=8,
                   color=C_BLUE, alpha=0.45, linewidths=0)
        ax.set_xscale("log")
        ax.set_yscale("log")
        for thr in (1_000, 10_000):
            ax.axvline(thr, color=C_GREY, lw=0.8, ls="--")
        ax.set_title(f"{LAB[m]}, glm_regional", color=C_INK, loc="left", fontsize=10)
        ax.set_xlabel("VIIRS detections in the country-year")
    axes[0].set_ylabel("|annual bias| (%), held-out country")
    fig.suptitle("Domain K-fold: error shrinks with country-year size (dashed: 1k and 10k tiers)",
                 x=0.01, ha="left", color=C_INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(root / "plots" / "bias_vs_size_kfold.png", dpi=150)


if __name__ == "__main__" and len(sys.argv) > 1:
    bias_vs_size(Path(sys.argv[1]))


def backcast_series(root):
    t = pd.read_csv(root / "backcast" / "backcast_annual_total.csv")
    t = t[t.year >= 2001]                       # 2000: MODIS Terra only from November
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.axvspan(2000.5, 2002.5, color="#f0efec", zorder=0)
    ax.axvspan(2011.5, 2024.5, color="#e8f0fa", zorder=0)
    ax.plot(t.year, t.harmonized_value / 1e6, color=C_BLUE, lw=2, marker="o", ms=4)
    ax.plot(t.year, t.modis_raw / 1e6, color=C_ORANGE, lw=2, marker="o", ms=4)
    v = t[t.year >= 2012]
    ax.plot(v.year, v.modis_as_viirs_equivalent / 1e6, color=C_AQUA, lw=2, marker="o", ms=4)
    for y, name in ((t.harmonized_value.iloc[-1], "Harmonized"), (t.modis_raw.iloc[-1], "Raw MODIS"),
                    (v.modis_as_viirs_equivalent.iloc[-1] * 1.06, "Calibrated MODIS")):
        ax.annotate(name, (2024.3, y / 1e6), va="center", color=C_INK, fontsize=8, annotation_clip=False)
    ax.text(2001.5, ax.get_ylim()[1] * 0.97, "Terra only", ha="center", va="top", color=C_MUTED, fontsize=8)
    ax.text(2018, ax.get_ylim()[1] * 0.97, "VIIRS era", ha="center", va="top", color=C_MUTED, fontsize=8)
    ax.set_xlim(2000.5, 2026.8)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Fire cell-days (millions)")
    ax.set_title("31 back-cast countries: fire cell-days per year, VIIRS-equivalent",
                 color=C_INK, loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(root / "plots" / "backcast_series.png", dpi=150)


if __name__ == "__main__" and len(sys.argv) > 1:
    backcast_series(Path(sys.argv[1]))
