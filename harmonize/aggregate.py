"""Grid/period aggregation (SCHEMA §2) and MODIS-vs-VIIRS pairing (SCHEMA §3).

Coverage design
---------------
A period is "covered" by a source if that source has >= 1 point of *any* type /
confidence in it, so coverage must come from the **unfiltered** points::

    raw = load_points(cfg)
    coverage = coverage_from_points(raw, cfg)      # {source: set(periods)}, incl. MODIS_ALL
    agg = aggregate(apply_filters(raw, cfg), cfg)
    paired = make_paired(agg, "MODIS_ALL", cfg, coverage=coverage)

If ``coverage`` is omitted, ``make_paired`` falls back to the periods present in
``agg`` itself (i.e. coverage after filtering) and emits a warning.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .config import MODIS_ALL, SOURCES_MODIS, Config

AGG_COLUMNS = ["source", "cell_id", "cell_lat", "cell_lon", "period", "period_start",
               "daynight", "n_hotspots", "fire_cell_days", "frp_sum"]
KEYS = ["cell_id", "period", "daynight"]
METRIC_COLS = ["n_hotspots", "fire_cell_days", "frp_sum"]


def _cell_indices(lat, lon, size):
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    iy = np.floor((lat + 90.0) / size).astype("int64")
    ix = np.floor((lon + 180.0) / size).astype("int64")
    return iy, ix


def _cell_strings(iy, ix):
    return pd.Series(iy).astype(str).str.cat(pd.Series(ix).astype(str), sep="_").to_numpy()


def cell_id_for(lat, lon, cell_size_deg: float):
    """``f"{iy}_{ix}"`` with iy = floor((lat+90)/size), ix = floor((lon+180)/size).

    Scalars give a str; array-likes give a numpy array of str.
    """
    if np.isscalar(lat) and np.isscalar(lon):
        iy, ix = _cell_indices([lat], [lon], cell_size_deg)
        return f"{iy[0]}_{ix[0]}"
    iy, ix = _cell_indices(lat, lon, cell_size_deg)
    return _cell_strings(iy, ix)


def cell_centre(iy, ix, cell_size_deg: float):
    """Cell centre (lat, lon), rounded to 6 dp."""
    iy = np.asarray(iy, dtype="float64")
    ix = np.asarray(ix, dtype="float64")
    return (np.round(-90.0 + (iy + 0.5) * cell_size_deg, 6),
            np.round(-180.0 + (ix + 0.5) * cell_size_deg, 6))


def period_for(datetime_utc, time_step: str):
    """UTC timestamp(s) -> period label: ``YYYY-MM`` (month) or ``YYYY-MM-DD`` (day)."""
    fmt = {"month": "%Y-%m", "day": "%Y-%m-%d"}.get(time_step)
    if fmt is None:
        raise ValueError(f"time_step must be 'month' or 'day', got {time_step!r}")
    if isinstance(datetime_utc, pd.Series):
        return datetime_utc.dt.tz_convert("UTC").dt.strftime(fmt).astype("str")
    if isinstance(datetime_utc, (pd.DatetimeIndex, np.ndarray, list)):
        idx = pd.DatetimeIndex(pd.to_datetime(datetime_utc, utc=True))
        return np.asarray(idx.strftime(fmt), dtype=object)
    return pd.Timestamp(datetime_utc).tz_convert("UTC").strftime(fmt) if pd.Timestamp(
        datetime_utc).tzinfo else pd.Timestamp(datetime_utc).strftime(fmt)


def period_start_for(period: pd.Series, time_step: str) -> pd.Series:
    return (period + "-01") if time_step == "month" else period.copy()


def _periods(points: pd.DataFrame, time_step: str) -> pd.Series:
    # acq_date is the UTC date as given; slicing it equals strftime on datetime_utc but is faster.
    d = points["datetime_utc"].dt.tz_convert("UTC")
    if time_step == "month":
        return (d.dt.year * 100 + d.dt.month).astype("int64")
    return (d.dt.year * 10000 + d.dt.month * 100 + d.dt.day).astype("int64")


def _period_label(code: pd.Series, time_step: str) -> pd.Series:
    s = code.astype("int64").astype(str)
    if time_step == "month":
        return s.str[:4] + "-" + s.str[4:6]
    return s.str[:4] + "-" + s.str[4:6] + "-" + s.str[6:8]


def coverage_from_points(points: pd.DataFrame, cfg: Config) -> dict[str, set[str]]:
    """{source: set(period labels)} where the source has >= 1 point (pass UNFILTERED points).

    Includes ``MODIS_ALL`` = union of Terra and Aqua coverage when any MODIS source exists.
    """
    if points.empty:
        return {}
    codes = _periods(points, cfg.time_step)
    df = pd.DataFrame({"source": points["source"].to_numpy(), "p": codes.to_numpy()})
    df = df.drop_duplicates()
    df["label"] = _period_label(df["p"], cfg.time_step).to_numpy()
    cov = {s: set(g["label"]) for s, g in df.groupby("source", sort=True)}
    modis = [cov[s] for s in SOURCES_MODIS if s in cov]
    if modis:
        cov[MODIS_ALL] = set().union(*modis)
    return cov


def aggregate(points: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Filtered points -> sparse long table (SCHEMA §2).

    ``MODIS_ALL`` (Terra ∪ Aqua) and ``daynight == "ALL"`` (D ∪ N) are built by
    duplicating point rows before grouping, so ``fire_cell_days`` is a true union of
    distinct UTC dates rather than a sum.
    """
    size = cfg.cell_size_deg
    if points.empty:
        return pd.DataFrame({c: pd.Series(dtype="int64" if c in ("n_hotspots", "fire_cell_days")
                                          else "float64" if c in ("cell_lat", "cell_lon", "frp_sum")
                                          else "str") for c in AGG_COLUMNS})
    iy, ix = _cell_indices(points["latitude"], points["longitude"], size)
    d = points["datetime_utc"].dt.tz_convert("UTC")
    day = (d.dt.year * 10000 + d.dt.month * 100 + d.dt.day).to_numpy("int64")
    base = pd.DataFrame({
        "source": points["source"].to_numpy(),
        "iy": iy, "ix": ix,
        "p": _periods(points, cfg.time_step).to_numpy(),
        "daynight": points["daynight"].to_numpy(),
        "day": day,
        "frp": points["frp"].to_numpy("float64"),
    })
    is_modis = base["source"].isin(SOURCES_MODIS).to_numpy()
    parts = [base]
    if is_modis.any():
        parts.append(base.loc[is_modis].assign(source=MODIS_ALL))
    srcs = pd.concat(parts, ignore_index=True)
    full = pd.concat([srcs, srcs.assign(daynight="ALL")], ignore_index=True)

    keys = ["source", "iy", "ix", "p", "daynight"]
    g = full.groupby(keys, sort=True, observed=True)
    out = g.agg(n_hotspots=("frp", "size"), frp_sum=("frp", "sum"),
                fire_cell_days=("day", "nunique")).reset_index()

    lat_c, lon_c = cell_centre(out["iy"], out["ix"], size)
    period = _period_label(out["p"], cfg.time_step)
    res = pd.DataFrame({
        "source": out["source"].astype("str"),
        "cell_id": _cell_strings(out["iy"].to_numpy(), out["ix"].to_numpy()),
        "cell_lat": lat_c, "cell_lon": lon_c,
        "period": period,
        "period_start": period_start_for(period, cfg.time_step),
        "daynight": out["daynight"].astype("str"),
        "n_hotspots": out["n_hotspots"].astype("int64"),
        "fire_cell_days": out["fire_cell_days"].astype("int64"),
        "frp_sum": out["frp_sum"].astype("float64"),
    })
    res["cell_id"] = res["cell_id"].astype("str")
    return res[AGG_COLUMNS].reset_index(drop=True)


def make_paired(agg: pd.DataFrame, modis_source: str, cfg: Config,
                coverage: dict[str, set[str]] | None = None) -> pd.DataFrame:
    """Zero-filled outer join of ``modis_source`` vs ``cfg.viirs_reference`` (SCHEMA §3).

    Keys = union of (cell_id, period, daynight) where either source has a row,
    restricted to periods covered by both. ``coverage`` should come from
    ``coverage_from_points(unfiltered_points, cfg)``; if None, coverage is inferred
    from ``agg`` (post-filter) with a warning.
    """
    viirs_source = cfg.viirs_reference
    if coverage is None:
        warnings.warn("make_paired: no coverage given; inferring covered periods from the "
                      "(filtered) aggregated table", stacklevel=2)
        coverage = {s: set(g) for s, g in agg.groupby("source")["period"]}
    both = coverage.get(modis_source, set()) & coverage.get(viirs_source, set())

    def side(src, prefix):
        s = agg.loc[(agg["source"] == src) & agg["period"].isin(both)]
        return s[["cell_id", "cell_lat", "cell_lon", "period", "period_start", "daynight",
                  *METRIC_COLS]].rename(columns={m: f"{prefix}_{m}" for m in METRIC_COLS})

    m, v = side(modis_source, "modis"), side(viirs_source, "viirs")
    merged = m.merge(v, on=KEYS, how="outer", suffixes=("_m", "_v"))
    for c in ("cell_lat", "cell_lon", "period_start"):
        merged[c] = merged[f"{c}_m"].fillna(merged[f"{c}_v"])
    for p in ("modis", "viirs"):
        merged[f"{p}_n_hotspots"] = merged[f"{p}_n_hotspots"].fillna(0).astype("int64")
        merged[f"{p}_fire_cell_days"] = merged[f"{p}_fire_cell_days"].fillna(0).astype("int64")
        merged[f"{p}_frp_sum"] = merged[f"{p}_frp_sum"].fillna(0.0).astype("float64")
    merged["modis_source"] = pd.Series(modis_source, index=merged.index, dtype="str")
    cols = ["cell_id", "cell_lat", "cell_lon", "period", "period_start", "daynight",
            "modis_n_hotspots", "modis_fire_cell_days", "modis_frp_sum",
            "viirs_n_hotspots", "viirs_fire_cell_days", "viirs_frp_sum", "modis_source"]
    merged["period_start"] = merged["period_start"].astype("str")
    return merged[cols].sort_values(KEYS, ignore_index=True)
