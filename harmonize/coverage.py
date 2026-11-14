"""Spatial + daily coverage (SCHEMA §2).

A file covers every coverage tile (``cfg.coverage_tile_deg``) its points touch, every day from
the first to the last ``acq_date`` of that file. For each source the range is clipped to that
source's observed span over all loaded files (its data-driven mission window), so a Terra+Aqua
file of 2002 does not mark Aqua as covering the months before Aqua's first data, while a sparse
country file whose last Terra fire is on Dec 6 still counts Terra as covering all of December.
Several files of the same source covering a tile are combined as a union of date intervals.

Known limitations (by construction, documented in the report / METHOD):
- a tile is "covered" for the whole date range even on days with no detection anywhere in the
  file (true for archives: no fire is a valid observation), but a file is assumed to have no
  temporal gaps inside its own [date_min, date_max];
- a tile touched only at the edge of a country file counts as fully covered, although part of
  the tile lies outside that country (both sensors' country files share the same border, so
  the bias cancels for joint coverage, but not when only one sensor's file is present);
- coverage is inferred from detections, so a tile with no fire at all in a file is not covered.

Implementation: per source, the merged intervals are stored as sorted int64 keys
``tile_code * 2**20 + day`` so that "is (tile, day) covered" is one ``np.searchsorted``.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .config import MODIS_ALL, Config

_BIG = 1 << 20           # > number of days in any plausible record
_DAY_OFF = 25567         # days 1900-01-01 -> 1970-01-01, keeps keys positive
_TAG_CHUNK = 2_000_000   # rows per vectorized block (bounds temporaries)
COVERAGE_COLUMNS = ["source_file", "source", "cov_tile", "date_min", "date_max"]
TAG_COLUMNS = ["cov_tile", "viirs_covered", "terra_covered", "aqua_covered", "modis_config"]
MODIS_CONFIG_LABELS = np.array([MODIS_ALL, "MODIS_TERRA", "MODIS_AQUA", "NONE"], dtype=object)


# --------------------------------------------------------------------------- small helpers
def tile_nx(size: float) -> int:
    return int(np.floor(360.0 / size)) + 2


def tile_codes(lat, lon, size: float) -> np.ndarray:
    """Same formula as cell_id: iy = floor((lat+90)/size), ix = floor((lon+180)/size)."""
    iy = np.floor((np.asarray(lat, dtype="float64") + 90.0) / size).astype("int64")
    ix = np.floor((np.asarray(lon, dtype="float64") + 180.0) / size).astype("int64")
    return iy * tile_nx(size) + ix


def tile_labels(codes: np.ndarray, size: float) -> np.ndarray:
    nx = tile_nx(size)
    codes = np.asarray(codes, dtype="int64")
    return (pd.Series(codes // nx).astype(str) + "_" + pd.Series(codes % nx).astype(str)).to_numpy()


def _parse_tile_labels(labels, size: float) -> np.ndarray:
    parts = pd.Series(labels, dtype="str").str.split("_", n=1, expand=True)
    return parts[0].astype("int64").to_numpy() * tile_nx(size) + parts[1].astype("int64").to_numpy()


def day_numbers(points: pd.DataFrame) -> np.ndarray:
    """Days since 1970-01-01 (int64) of each point's UTC ``acq_date`` (fallback ``datetime_utc``)."""
    if "acq_date" in points.columns:
        s = points["acq_date"]
        if isinstance(s.dtype, pd.CategoricalDtype):
            cats, codes = s.cat.categories, s.cat.codes.to_numpy()
        else:
            codes, cats = pd.factorize(s)
        d = pd.to_datetime(pd.Index(cats).astype(str), format="%Y-%m-%d").to_numpy(
            "datetime64[D]").astype("int64")
        return d[codes] if len(d) else np.zeros(len(points), "int64")
    dt = points["datetime_utc"]
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_convert("UTC").dt.tz_localize(None)
    return dt.to_numpy("datetime64[D]").astype("int64")


def _codes(s: pd.Series):
    if isinstance(s.dtype, pd.CategoricalDtype):
        return s.cat.codes.to_numpy(), pd.Index(s.cat.categories)
    codes, uniq = pd.factorize(s)
    return codes, pd.Index(uniq)


# --------------------------------------------------------------------------- build
def build_coverage(points_all: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """UNFILTERED points -> one row per (source_file, source, cov_tile) with date_min/date_max
    (first/last acq_date of that file for that source)."""
    if len(points_all) == 0:
        return pd.DataFrame({c: pd.Series(dtype="datetime64[ns]" if c.startswith("date") else "str")
                             for c in COVERAGE_COLUMNS})
    size = cfg.coverage_tile_deg
    fcode, fcats = _codes(points_all["source_file"])
    scode, scats = _codes(points_all["source"])
    ns = len(scats) + 1
    nrow = len(points_all)
    # unique (file, source, day) and (file, source, tile) keys, built chunk by chunk
    fsd, fst = [], []
    for lo in range(0, nrow, _TAG_CHUNK):
        sl = slice(lo, lo + _TAG_CHUNK)
        fs = fcode[sl].astype("int64") * ns + scode[sl]
        sub = points_all.iloc[sl]
        fsd.append(pd.unique(fs * _BIG + day_numbers(sub) + _DAY_OFF))
        fst.append(pd.unique(fs * (1 << 40) + tile_codes(sub["latitude"], sub["longitude"], size)))
    fsd = pd.unique(np.concatenate(fsd))
    uk = pd.unique(np.concatenate(fst))
    del fst
    dd = pd.DataFrame({"f": (fsd // _BIG) // ns, "s": (fsd // _BIG) % ns, "fs": fsd // _BIG,
                       "day": fsd % _BIG - _DAY_OFF})
    # file date range, clipped to the source's observed span over ALL files (its mission window)
    frng = dd.groupby("f")["day"].agg(["min", "max"])
    srng = dd.groupby("s")["day"].agg(["min", "max"])
    ufs_all = pd.Index(pd.unique(dd["fs"].to_numpy()))
    f_of, s_of = ufs_all.to_numpy() // ns, ufs_all.to_numpy() % ns
    rng = pd.DataFrame({
        "min": np.maximum(frng["min"].reindex(f_of).to_numpy(), srng["min"].reindex(s_of).to_numpy()),
        "max": np.minimum(frng["max"].reindex(f_of).to_numpy(), srng["max"].reindex(s_of).to_numpy()),
    }, index=ufs_all)
    ufs, utile = uk >> 40, uk & ((1 << 40) - 1)
    order = np.lexsort((utile, ufs))
    ufs, utile = ufs[order], utile[order]
    dmin = rng["min"].reindex(ufs).to_numpy()
    dmax = rng["max"].reindex(ufs).to_numpy()
    out = pd.DataFrame({
        "source_file": np.asarray(fcats)[ufs // ns],
        "source": np.asarray(scats)[ufs % ns],
        "cov_tile": tile_labels(utile, size),
        "date_min": dmin.astype("datetime64[D]").astype("datetime64[ns]"),
        "date_max": dmax.astype("datetime64[D]").astype("datetime64[ns]"),
    })
    for c in ("source_file", "source", "cov_tile"):
        out[c] = out[c].astype("str")
    return out


class CoverageIndex:
    """Merged coverage intervals per source; answers "is (tile, day) covered by source s"."""

    def __init__(self, coverage: pd.DataFrame, cfg: Config):
        self.tile_deg = float(cfg.coverage_tile_deg)
        self.viirs_reference = cfg.viirs_reference
        self.intervals: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        if len(coverage) == 0:
            return
        tiles = _parse_tile_labels(coverage["cov_tile"], self.tile_deg)
        d0 = coverage["date_min"].to_numpy("datetime64[D]").astype("int64") + _DAY_OFF
        d1 = coverage["date_max"].to_numpy("datetime64[D]").astype("int64") + _DAY_OFF
        src = coverage["source"].astype(str).to_numpy()
        for s in np.unique(src):
            m = src == s
            ks, ke = tiles[m] * _BIG + d0[m], tiles[m] * _BIG + d1[m]
            o = np.argsort(ks, kind="stable")
            ks, ke = ks[o], ke[o]
            run_end = np.maximum.accumulate(ke)
            new = np.ones(len(ks), bool)
            new[1:] = ks[1:] > run_end[:-1] + 1          # gap -> new interval (adjacent days merge)
            starts_idx = np.flatnonzero(new)
            self.intervals[s] = (ks[starts_idx], np.maximum.reduceat(ke, starts_idx))

    # pandas deep-copies attrs on most operations; the index is immutable, so share it
    def __deepcopy__(self, memo):
        return self

    def __copy__(self):
        return self

    def sources(self) -> list[str]:
        return sorted(self.intervals)

    def covered(self, source: str, tiles: np.ndarray, days: np.ndarray) -> np.ndarray:
        """bool array: ``source`` covers tile ``tiles[i]`` on day ``days[i]`` (days since 1970)."""
        tiles = np.asarray(tiles, dtype="int64")
        if source not in self.intervals or len(tiles) == 0:
            return np.zeros(len(tiles), bool)
        starts, ends = self.intervals[source]
        q = tiles * _BIG + np.asarray(days, dtype="int64") + _DAY_OFF
        i = np.searchsorted(starts, q, side="right") - 1
        ok = i >= 0
        ok[ok] = q[ok] <= ends[i[ok]]
        return ok

    def flags(self, tiles, days):
        v = self.covered(self.viirs_reference, tiles, days)
        t = self.covered("MODIS_TERRA", tiles, days)
        a = self.covered("MODIS_AQUA", tiles, days)
        return v, t, a


def get_index(points_tagged: pd.DataFrame | None, cfg: Config, coverage=None) -> CoverageIndex | None:
    """Coverage index from an explicit ``coverage`` (table or index) or from the tagged points'
    ``attrs['coverage_index']`` (set by ``tag_points``)."""
    if isinstance(coverage, CoverageIndex):
        return coverage
    if isinstance(coverage, pd.DataFrame):
        return CoverageIndex(coverage, cfg)
    if points_tagged is not None:
        idx = points_tagged.attrs.get("coverage_index")
        if isinstance(idx, CoverageIndex):
            return idx
    return None


# --------------------------------------------------------------------------- tagging
def modis_config_codes(terra: np.ndarray, aqua: np.ndarray) -> np.ndarray:
    """0 = MODIS_ALL, 1 = MODIS_TERRA, 2 = MODIS_AQUA, 3 = NONE."""
    return np.select([terra & aqua, terra, aqua], [0, 1, 2], 3).astype("int8")


def tag_points(points: pd.DataFrame, coverage, cfg: Config) -> pd.DataFrame:
    """Add cov_tile, viirs_covered, terra_covered, aqua_covered, modis_config (SCHEMA §2).

    ``coverage`` is the ``build_coverage`` table (or a ``CoverageIndex``). The index is attached
    as ``attrs['coverage_index']`` so ``make_paired`` / ``build_harmonized`` can count covered days.
    """
    idx = get_index(None, cfg, coverage)
    size = cfg.coverage_tile_deg
    n = len(points)
    v, t, a = (np.zeros(n, bool) for _ in range(3))
    tcode = np.zeros(n, "int64")
    for lo in range(0, n, _TAG_CHUNK):
        sl = slice(lo, lo + _TAG_CHUNK)
        sub = points.iloc[sl]
        tiles = tile_codes(sub["latitude"], sub["longitude"], size)
        v[sl], t[sl], a[sl] = idx.flags(tiles, day_numbers(sub))
        tcode[sl] = tiles
    codes, ucodes = pd.factorize(tcode)
    del tcode
    cov_tile = pd.Categorical.from_codes(codes.astype("int32"),
                                         categories=pd.Index(tile_labels(np.asarray(ucodes), size)))
    mc = modis_config_codes(t, a)
    out = points.assign(
        cov_tile=cov_tile, viirs_covered=v, terra_covered=t, aqua_covered=a,
        modis_config=pd.Categorical.from_codes(mc, categories=pd.Index(list(MODIS_CONFIG_LABELS))),
    )
    out.attrs["coverage_index"] = idx
    return out


# --------------------------------------------------------------------------- day counts
def period_day_table(period_codes: np.ndarray, time_step: str):
    """For unique period codes (YYYYMM or YYYYMMDD ints) -> (period_code_rep, day) enumerating
    every day of each period (days since 1970)."""
    pcs, days = [], []
    for pc in np.unique(np.asarray(period_codes, dtype="int64")):
        if time_step == "month":
            y, m = divmod(int(pc), 100)
            start = np.datetime64(f"{y:04d}-{m:02d}-01", "D")
            end = (np.datetime64(f"{y:04d}-{m:02d}", "M") + np.timedelta64(1, "M")).astype("datetime64[D]")
        else:
            y, r = divmod(int(pc), 10000)
            m, dd = divmod(r, 100)
            start = np.datetime64(f"{y:04d}-{m:02d}-{dd:02d}", "D")
            end = start + np.timedelta64(1, "D")
        rng = np.arange(start, end).astype("int64")
        days.append(rng)
        pcs.append(np.full(len(rng), pc, dtype="int64"))
    if not days:
        return np.zeros(0, "int64"), np.zeros(0, "int64")
    return np.concatenate(pcs), np.concatenate(days)


def covered_day_counts(tiles: np.ndarray, periods: np.ndarray, cfg: Config,
                       index: CoverageIndex | None = None,
                       points_tagged: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per unique (tile, period) pair: how many days are covered by each combination.

    Returns columns tile, pcode, n_viirs, n_modis_all (V & T & A), n_modis_terra (V & T),
    n_modis_aqua (V & A), n_modis_only ((T | A) & ~V), n_modis_any (T | A).
    The ``n_modis_*`` joint counts follow the make_paired rule for each modis_source.

    Without an index, falls back (with a warning) to days on which the tagged points themselves
    show the flags — an under-estimate on fire-free days.
    """
    pairs = pd.DataFrame({"tile": np.asarray(tiles, "int64"), "pcode": np.asarray(periods, "int64")})
    pairs = pairs.drop_duplicates(ignore_index=True)
    cols = ["n_viirs", "n_modis_all", "n_modis_terra", "n_modis_aqua", "n_modis_only", "n_modis_any"]
    if pairs.empty:
        return pairs.assign(**{c: np.zeros(0, "int64") for c in cols})
    if index is not None:
        pc_rep, day_rep = period_day_table(pairs["pcode"].to_numpy(), cfg.time_step)
        days_per = pd.DataFrame({"pcode": pc_rep, "day": day_rep})
        grid = pairs.merge(days_per, on="pcode", how="inner")
        v, t, a = index.flags(grid["tile"].to_numpy(), grid["day"].to_numpy())
    else:
        if points_tagged is None:
            raise ValueError("covered_day_counts needs a coverage index or tagged points")
        warnings.warn("no coverage index (use tag_points or pass coverage=); counting covered days "
                      "from the points themselves", stacklevel=3)
        from .aggregate import period_codes_from_days
        size = cfg.coverage_tile_deg
        days = day_numbers(points_tagged)
        g = pd.DataFrame({
            "tile": tile_codes(points_tagged["latitude"], points_tagged["longitude"], size),
            "day": days, "pcode": period_codes_from_days(days, cfg.time_step),
            "v": points_tagged["viirs_covered"].to_numpy(bool),
            "t": points_tagged["terra_covered"].to_numpy(bool),
            "a": points_tagged["aqua_covered"].to_numpy(bool),
        }).groupby(["tile", "pcode", "day"], as_index=False)[["v", "t", "a"]].max()
        grid = pairs.merge(g, on=["tile", "pcode"], how="inner")
        v, t, a = (grid[c].to_numpy(bool) for c in ("v", "t", "a"))
    flags = pd.DataFrame({
        "tile": grid["tile"].to_numpy(), "pcode": grid["pcode"].to_numpy(),
        "n_viirs": v, "n_modis_all": v & t & a, "n_modis_terra": v & t, "n_modis_aqua": v & a,
        "n_modis_only": (t | a) & ~v, "n_modis_any": t | a,
    })
    counts = flags.groupby(["tile", "pcode"], as_index=False)[cols].sum()
    out = pairs.merge(counts, on=["tile", "pcode"], how="left")
    out[cols] = out[cols].fillna(0).astype("int64")
    return out
