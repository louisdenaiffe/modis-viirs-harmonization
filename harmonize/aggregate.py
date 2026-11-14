"""Grid/period aggregation (SCHEMA §3) and MODIS-vs-VIIRS pairing on jointly covered tile-days
(SCHEMA §4).

Usage::

    raw = load_points(cfg)
    cov = build_coverage(raw, cfg)                       # unfiltered points
    pts = tag_points(apply_filters(raw, cfg), cov, cfg)  # attaches the coverage index
    agg = aggregate(pts, cfg)
    paired = make_paired(pts, "MODIS_ALL", cfg)

Internally everything is grouped on a single int64 key
``(cell_code * 4 + config_code) * 10**8 + period_code`` (no string keys until the end), and
``MODIS_ALL`` / ``daynight == ALL`` are computed as separate passes over the relevant points, so
no point rows are duplicated in memory and ``fire_cell_days`` is a true union of UTC dates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import MODIS_ALL, SOURCES_MODIS, Config
from .coverage import (MODIS_CONFIG_LABELS, covered_day_counts, day_numbers, get_index,
                       tile_codes)

FEATURE_COLS = ["frp_mean", "frp_p90", "scan_mean", "bright_mir_mean", "n_terra", "n_aqua"]
METRIC_COLS = ["n_hotspots", "fire_cell_days", "frp_sum"]
AGG_COLUMNS = ["source", "cell_id", "cell_lat", "cell_lon", "period", "period_start", "daynight",
               *METRIC_COLS, *FEATURE_COLS, "domain"]
KEYS = ["cell_id", "period", "daynight"]
PAIRED_COLUMNS = (["cell_id", "cell_lat", "cell_lon", "period", "period_start", "daynight",
                   "domain", "modis_source"]
                  + [f"modis_{m}" for m in METRIC_COLS] + [f"viirs_{m}" for m in METRIC_COLS]
                  + [f"modis_{f}" for f in FEATURE_COLS] + ["viirs_frp_mean", "n_days_covered"])
_P = 10 ** 8          # period code slot (YYYYMMDD < 1e8)
_NCONF = 4
_DN = ("D", "N", "ALL")
_JOINT_COUNT = {MODIS_ALL: "n_modis_all", "MODIS_TERRA": "n_modis_terra",
                "MODIS_AQUA": "n_modis_aqua"}


# --------------------------------------------------------------------------- cell / period
def _nx(size: float) -> int:
    return int(np.floor(360.0 / size)) + 2


def _cell_indices(lat, lon, size):
    iy = np.floor((np.asarray(lat, dtype="float64") + 90.0) / size).astype("int64")
    ix = np.floor((np.asarray(lon, dtype="float64") + 180.0) / size).astype("int64")
    return iy, ix


def _cell_strings(iy, ix):
    return (pd.Series(np.asarray(iy)).astype(str) + "_"
            + pd.Series(np.asarray(ix)).astype(str)).to_numpy()


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
    ts = pd.Timestamp(datetime_utc)
    return (ts.tz_convert("UTC") if ts.tzinfo else ts).strftime(fmt)


def period_codes_from_days(days: np.ndarray, time_step: str) -> np.ndarray:
    """Days since 1970 -> YYYYMM (month) or YYYYMMDD (day) int64 codes."""
    d = np.asarray(days, dtype="int64").astype("datetime64[D]")
    m = d.astype("datetime64[M]").astype("int64")
    y, mo = m // 12 + 1970, m % 12 + 1
    if time_step == "month":
        return y * 100 + mo
    if time_step == "day":
        dom = (d - d.astype("datetime64[M]").astype("datetime64[D]")).astype("int64") + 1
        return y * 10000 + mo * 100 + dom
    raise ValueError(f"time_step must be 'month' or 'day', got {time_step!r}")


def _period_labels(codes: np.ndarray, time_step: str) -> np.ndarray:
    u, inv = np.unique(np.asarray(codes, dtype="int64"), return_inverse=True)
    s = pd.Series(u).astype(str)
    lab = (s.str[:4] + "-" + s.str[4:6]) if time_step == "month" else (
        s.str[:4] + "-" + s.str[4:6] + "-" + s.str[6:8])
    return lab.to_numpy()[inv]


def period_start_labels(labels, time_step: str) -> np.ndarray:
    labels = pd.Series(labels, dtype="str")
    return (labels + "-01").to_numpy() if time_step == "month" else labels.to_numpy()


def days_in_period(pcodes: np.ndarray, time_step: str) -> np.ndarray:
    pcodes = np.asarray(pcodes, dtype="int64")
    if time_step == "day":
        return np.ones(len(pcodes), "int64")
    m = (pcodes // 100 - 1970) * 12 + (pcodes % 100 - 1)
    m = m.astype("datetime64[M]")
    return ((m + np.timedelta64(1, "M")).astype("datetime64[D]") - m.astype("datetime64[D]")).astype("int64")


# --------------------------------------------------------------------------- core grouping
CHUNK_ROWS = 2_000_000      # points per aggregation chunk (bounds temporary memory)


def _codes(s: pd.Series):
    if isinstance(s.dtype, pd.CategoricalDtype):
        return s.cat.codes.to_numpy(), pd.Index(s.cat.categories).astype(str)
    codes, uniq = pd.factorize(s.astype(str))
    return codes, pd.Index(uniq).astype(str)


class PointView:
    """Zero-copy column views of a points table; builds per-chunk integer keys on demand.

    Chunks are contiguous bands of cell rows (iy), so a (cell, period) group never spans chunks.
    """

    def __init__(self, points: pd.DataFrame, cfg: Config):
        self.cfg, self.n = cfg, len(points)
        self.lat = points["latitude"].to_numpy("float64")
        self.lon = points["longitude"].to_numpy("float64")
        self.src, self.src_cats = _codes(points["source"])
        dn, dn_cats = _codes(points["daynight"])
        dn_map = np.array([0 if c == "D" else 1 if c == "N" else 2 for c in dn_cats] + [2], "int8")
        self.dn, self.dn_map = dn, dn_map
        if "acq_date" in points.columns and isinstance(points["acq_date"].dtype, pd.CategoricalDtype):
            self.day_codes = points["acq_date"].cat.codes.to_numpy()
            self.day_lut = day_numbers(pd.DataFrame({"acq_date": pd.Categorical(
                points["acq_date"].cat.categories)})).astype("int32")
        else:
            self.day_codes, self.day_lut = None, day_numbers(points).astype("int32")
        self.cols = {c: points[c].to_numpy() if c in points.columns else None
                     for c in ("frp", "scan", "bright_mir_k", "viirs_covered", "terra_covered",
                               "aqua_covered")}
        if "domain" in points.columns:
            self.dom, self.dom_cats = _codes(points["domain"])
        else:
            self.dom, self.dom_cats = np.zeros(self.n, "int8"), pd.Index([""])
        if "modis_config" in points.columns:
            c, cats = _codes(points["modis_config"])
            lut = np.array([list(MODIS_CONFIG_LABELS).index(x) if x in set(MODIS_CONFIG_LABELS)
                            else 3 for x in cats] + [3], "int8")
            self.conf = lut[c]
        else:
            self.conf = None

    def code(self, label: str) -> int:
        return int(self.src_cats.get_loc(label)) if label in self.src_cats else -99

    def chunks(self, max_rows: int | None = None):
        max_rows = max_rows or CHUNK_ROWS
        if self.n <= max_rows:
            yield None
            return
        iy = np.floor((self.lat + 90.0) / self.cfg.cell_size_deg).astype("int32")
        lo = int(iy.min())
        counts = np.bincount(iy - lo)
        start, acc = 0, 0
        for r, c in enumerate(counts):
            acc += c
            if acc >= max_rows or r == len(counts) - 1:
                yield np.flatnonzero((iy >= start + lo) & (iy <= r + lo))
                start, acc = r + 1, 0

    def base(self, idx) -> dict:
        take = (lambda a: a) if idx is None else (lambda a: a[idx])
        size = self.cfg.cell_size_deg
        iy, ix = _cell_indices(take(self.lat), take(self.lon), size)
        day = self.day_lut[take(self.day_codes)] if self.day_codes is not None else take(self.day_lut)
        pcode = period_codes_from_days(day, self.cfg.time_step)
        src = take(self.src)
        t_code, a_code = self.code("MODIS_TERRA"), self.code("MODIS_AQUA")
        nan = np.full(len(src), np.nan, "float32")
        col = lambda c, dt: take(self.cols[c]).astype(dt, copy=False) if self.cols[c] is not None \
            else nan  # noqa: E731
        b = {"key0": (iy * _nx(size) + ix) * (_NCONF * _P) + pcode, "day": day,
             "dn": self.dn_map[take(self.dn)], "src": src,
             "terra": src == t_code, "aqua": src == a_code,
             "frp": col("frp", "float64"), "scan": col("scan", "float32"),
             "mir": col("bright_mir_k", "float32"), "dom": take(self.dom)}
        for c, k in (("viirs_covered", "v"), ("terra_covered", "t"), ("aqua_covered", "a")):
            if self.cols[c] is not None:
                b[k] = take(self.cols[c]).astype(bool, copy=False)
        if self.conf is not None:
            b["conf"] = take(self.conf).astype("int64")
        return b


def _group(b: dict, mask: np.ndarray, by_config: bool) -> pd.DataFrame:
    """Aggregate the masked points by key -> one row per key with metrics, features, domain."""
    k = b["key0"][mask]
    if by_config:
        k = k + b["conf"][mask] * _P
    df = pd.DataFrame({"key": k, "frp": b["frp"][mask], "scan": b["scan"][mask],
                       "mir": b["mir"][mask], "terra": b["terra"][mask].astype("int32"),
                       "aqua": b["aqua"][mask].astype("int32")})
    g = df.groupby("key", sort=True)
    res = g.agg(n_hotspots=("frp", "size"), frp_sum=("frp", "sum"), frp_mean=("frp", "mean"),
                scan_mean=("scan", "mean"), bright_mir_mean=("mir", "mean"),
                n_terra=("terra", "sum"), n_aqua=("aqua", "sum"))
    res["frp_p90"] = g["frp"].quantile(0.9)
    del df, g
    kd = pd.DataFrame({"key": k, "day": b["day"][mask]}).drop_duplicates()
    res["fire_cell_days"] = kd.groupby("key").size()
    del kd
    dom = pd.DataFrame({"key": k, "dom": b["dom"][mask]}).value_counts().reset_index(name="c")
    dom = dom.sort_values(["key", "c", "dom"], ascending=[True, False, True]).drop_duplicates("key")
    res["dom"] = dom.set_index("key")["dom"]
    return res.reset_index()


_RAW_COLS = ["key", "n_hotspots", "frp_sum", "frp_mean", "scan_mean", "bright_mir_mean", "n_terra",
             "n_aqua", "frp_p90", "fire_cell_days", "dom", "daynight"]


def run_selections(points: pd.DataFrame, cfg: Config, selections, max_rows: int | None = None,
                   view: PointView | None = None) -> dict:
    """Aggregate several point selections in one chunked pass.

    ``selections``: list of ``(name, by_config, maskfn)``, ``maskfn(base, view) -> bool array``.
    Each selection's points are treated as ONE source. Returns ``{name: raw}`` with int ``key``,
    ``daynight`` (D/N/ALL) and the metric / feature columns; ``raw.attrs['dom_cats']``.
    """
    view = view or PointView(points, cfg)
    parts = {name: [] for name, _, _ in selections}
    for idx in view.chunks(max_rows):
        b = view.base(idx)
        for name, by_config, fn in selections:
            m0 = fn(b, view)
            if not m0.any():
                continue
            for dcode, dn in ((0, "D"), (1, "N"), (None, "ALL")):
                m = m0 if dcode is None else (m0 & (b["dn"] == dcode))
                if m.any():
                    r = _group(b, m, by_config)
                    r["daynight"] = dn
                    parts[name].append(r)
        del b
    out = {}
    for name, ps in parts.items():
        if ps:
            r = pd.concat(ps, ignore_index=True)
        else:
            r = pd.DataFrame({c: np.zeros(0, "int64") for c in _RAW_COLS})
            r["daynight"] = r["daynight"].astype("str")
        r.attrs["dom_cats"] = list(view.dom_cats)
        out[name] = r
    return out


def _aggregate_raw(points: pd.DataFrame, cfg: Config, by_config: bool = False) -> pd.DataFrame:
    """All given points treated as ONE source -> raw rows keyed by int (key, daynight)."""
    return run_selections(points, cfg, [("x", by_config, lambda b, v: np.ones(len(b["src"]), bool))])["x"]


def _decode(raw: pd.DataFrame, cfg: Config, dom_cats) -> pd.DataFrame:
    """Int key -> cell_id / cell_lat / cell_lon / period / period_start / modis_config / domain."""
    key = raw["key"].to_numpy("int64")
    pcode = key % _P
    cc = key // _P
    conf, cell = cc % _NCONF, cc // _NCONF
    nx = _nx(cfg.cell_size_deg)
    ucell, inv = np.unique(cell, return_inverse=True)
    iy, ix = ucell // nx, ucell % nx
    lat, lon = cell_centre(iy, ix, cfg.cell_size_deg)
    period = _period_labels(pcode, cfg.time_step)
    dom = raw["dom"].to_numpy()
    dcats = np.asarray(list(dom_cats) + [""], dtype=object)
    dom = np.where(pd.isna(dom), len(dcats) - 1, dom).astype("int64") if len(dom) else dom.astype("int64")
    return pd.DataFrame({
        "cell_id": pd.array(_cell_strings(iy, ix)[inv] if len(ucell) else np.zeros(0, str), dtype="str"),
        "cell_lat": lat[inv], "cell_lon": lon[inv],
        "period": pd.array(period, dtype="str"),
        "period_start": pd.array(period_start_labels(period, cfg.time_step), dtype="str"),
        "modis_config": MODIS_CONFIG_LABELS[conf],
        "domain": pd.array(dcats[dom], dtype="str"),
        "_cell": cell, "_pcode": pcode,
    }, index=raw.index)


def _finalize(raw: pd.DataFrame, source_label, cfg: Config, by_config: bool) -> pd.DataFrame:
    d = _decode(raw, cfg, raw.attrs.get("dom_cats", [""]))
    out = pd.DataFrame({
        "source": pd.array(np.broadcast_to(np.asarray(source_label, dtype=object), len(raw)),
                           dtype="str"),
        "cell_id": d["cell_id"], "cell_lat": d["cell_lat"], "cell_lon": d["cell_lon"],
        "period": d["period"], "period_start": d["period_start"],
        "daynight": pd.array(raw["daynight"].astype(str).to_numpy(), dtype="str"),
        "n_hotspots": raw["n_hotspots"].to_numpy("int64"),
        "fire_cell_days": raw["fire_cell_days"].to_numpy("int64"),
        "frp_sum": raw["frp_sum"].to_numpy("float64"),
        "frp_mean": raw["frp_mean"].to_numpy("float64"),
        "frp_p90": raw["frp_p90"].to_numpy("float64"),
        "scan_mean": raw["scan_mean"].to_numpy("float64"),
        "bright_mir_mean": raw["bright_mir_mean"].to_numpy("float64"),
        "n_terra": raw["n_terra"].to_numpy("int64"),
        "n_aqua": raw["n_aqua"].to_numpy("int64"),
        "domain": d["domain"],
    })
    cols = list(AGG_COLUMNS)
    if by_config:
        out["modis_config"] = pd.array(d["modis_config"].to_numpy(), dtype="str")
        cols.insert(cols.index("daynight") + 1, "modis_config")
    return out[cols]


def _empty_agg(by_config: bool) -> pd.DataFrame:
    types = {"n_hotspots": "int64", "fire_cell_days": "int64", "n_terra": "int64", "n_aqua": "int64",
             "cell_lat": "float64", "cell_lon": "float64", "frp_sum": "float64",
             "frp_mean": "float64", "frp_p90": "float64", "scan_mean": "float64",
             "bright_mir_mean": "float64"}
    cols = list(AGG_COLUMNS)
    if by_config:
        cols.insert(cols.index("daynight") + 1, "modis_config")
    return pd.DataFrame({c: pd.Series(dtype=types.get(c, "str")) for c in cols})


# --------------------------------------------------------------------------- public
def aggregate(points: pd.DataFrame, cfg: Config, by_config: bool = False) -> pd.DataFrame:
    """Filtered points -> sparse long table (SCHEMA §3): one row per
    (source, cell_id, period, daynight[, modis_config]) with n_hotspots > 0.

    ``source`` = each point source plus ``MODIS_ALL`` (Terra ∪ Aqua); ``daynight`` = D, N, ALL.
    ``by_config=True`` needs ``modis_config`` (from ``tag_points``) and adds it to the key.
    """
    if len(points) == 0:
        return _empty_agg(by_config)
    if by_config and "modis_config" not in points.columns:
        raise ValueError("aggregate(by_config=True) needs tagged points (tag_points)")
    view = PointView(points, cfg)
    present = sorted(set(view.src_cats[np.unique(view.src[view.src >= 0])]))
    sels = [(s, by_config, (lambda c: lambda b, v: b["src"] == c)(view.code(s))) for s in present]
    if any(s in SOURCES_MODIS for s in present):
        sels.append((MODIS_ALL, by_config, lambda b, v: b["terra"] | b["aqua"]))
    raws = run_selections(points, cfg, sels, view=view)
    out = pd.concat([_finalize(raws[name], name, cfg, by_config) for name, _, _ in sels],
                    ignore_index=True)
    key = ["source", "cell_id", "period", "daynight"] + (["modis_config"] if by_config else [])
    return out.sort_values(key, ignore_index=True)


def _joint(b: dict, modis_source: str) -> np.ndarray:
    if "v" not in b:
        raise ValueError("make_paired needs tagged points (coverage.tag_points)")
    if modis_source == MODIS_ALL:
        return b["v"] & (b["conf"] == 0)
    if modis_source == "MODIS_AQUA":
        return b["v"] & b["a"]
    return b["v"] & b["t"]


def _side(raw: pd.DataFrame, cfg: Config, prefix: str, with_features: bool) -> pd.DataFrame:
    d = _decode(raw, cfg, raw.attrs["dom_cats"])
    out = pd.DataFrame({"_cell": d["_cell"].to_numpy(), "_pcode": d["_pcode"].to_numpy(),
                        "daynight": raw["daynight"].astype(str).to_numpy(),
                        f"{prefix}_domain": d["domain"].to_numpy()})
    for m in METRIC_COLS:
        out[f"{prefix}_{m}"] = raw[m].to_numpy()
    for f in (FEATURE_COLS if with_features else ["frp_mean"]):
        out[f"{prefix}_{f}"] = raw[f].to_numpy("float64")
    return out


def _cell_meta(cell: np.ndarray, pcode: np.ndarray, cfg: Config) -> dict:
    nx = _nx(cfg.cell_size_deg)
    ucell, inv = np.unique(cell, return_inverse=True)
    iy, ix = ucell // nx, ucell % nx
    lat, lon = cell_centre(iy, ix, cfg.cell_size_deg)
    period = _period_labels(pcode, cfg.time_step)
    ids = _cell_strings(iy, ix) if len(ucell) else np.zeros(0, str)
    return {"cell_id": pd.array(ids[inv], dtype="str"), "cell_lat": lat[inv], "cell_lon": lon[inv],
            "period": pd.array(period, dtype="str"),
            "period_start": pd.array(period_start_labels(period, cfg.time_step), dtype="str"),
            "_lat": lat[inv], "_lon": lon[inv]}


def make_paired(points_tagged: pd.DataFrame, modis_source: str, cfg: Config,
                coverage=None) -> pd.DataFrame:
    """Zero-filled outer join of ``modis_source`` vs ``cfg.viirs_reference`` restricted to tile-days
    covered by BOTH (SCHEMA §4). ``points_tagged`` = filtered points from ``tag_points``.

    ``n_days_covered`` (jointly covered days in the cell's coverage tile and period) needs the
    coverage index: taken from ``points_tagged.attrs`` (set by ``tag_points``) unless
    ``coverage`` (table or ``CoverageIndex``) is passed.
    """
    if modis_source not in _JOINT_COUNT:
        raise ValueError(f"modis_source must be one of {list(_JOINT_COUNT)}; got {modis_source!r}")
    view = PointView(points_tagged, cfg)
    if view.conf is None:
        raise ValueError("make_paired needs tagged points (coverage.tag_points)")
    vcode = view.code(cfg.viirs_reference)
    mcodes = [view.code(s) for s in (SOURCES_MODIS if modis_source == MODIS_ALL else (modis_source,))]
    raws = run_selections(points_tagged, cfg, [
        ("modis", False, lambda b, v: _joint(b, modis_source) & np.isin(b["src"], mcodes)),
        ("viirs", False, lambda b, v: _joint(b, modis_source) & (b["src"] == vcode)),
    ], view=view)
    m = _side(raws["modis"], cfg, "modis", True)
    v = _side(raws["viirs"], cfg, "viirs", False)
    del raws
    merged = m.merge(v, on=["_cell", "_pcode", "daynight"], how="outer")
    for p in ("modis", "viirs"):
        for c in ("n_hotspots", "fire_cell_days"):
            merged[f"{p}_{c}"] = merged[f"{p}_{c}"].fillna(0).astype("int64")
        merged[f"{p}_frp_sum"] = merged[f"{p}_frp_sum"].fillna(0.0).astype("float64")
    for f in ("n_terra", "n_aqua"):
        merged[f"modis_{f}"] = merged[f"modis_{f}"].astype("float64")  # NaN where MODIS = 0
    meta = _cell_meta(merged["_cell"].to_numpy("int64"), merged["_pcode"].to_numpy("int64"), cfg)
    for k in ("cell_id", "cell_lat", "cell_lon", "period", "period_start"):
        merged[k] = meta[k]
    md, vd = merged["modis_domain"], merged["viirs_domain"]
    use_m = md.notna().to_numpy() & (merged["modis_n_hotspots"].to_numpy()
                                     >= merged["viirs_n_hotspots"].to_numpy())
    merged["domain"] = pd.array(np.where(use_m | vd.isna().to_numpy(), md.to_numpy(object),
                                         vd.to_numpy(object)), dtype="str")
    merged["modis_source"] = pd.array(np.full(len(merged), modis_source, dtype=object), dtype="str")
    merged["daynight"] = pd.array(merged["daynight"].to_numpy(object), dtype="str")

    tiles = tile_codes(meta["_lat"], meta["_lon"], cfg.coverage_tile_deg)
    idx = get_index(points_tagged, cfg, coverage)
    cnt = covered_day_counts(tiles, merged["_pcode"].to_numpy(), cfg, index=idx,
                             points_tagged=None if idx is not None else points_tagged)
    look = pd.DataFrame({"tile": tiles, "pcode": merged["_pcode"].to_numpy("int64")}).merge(
        cnt[["tile", "pcode", _JOINT_COUNT[modis_source]]], on=["tile", "pcode"], how="left")
    merged["n_days_covered"] = look[_JOINT_COUNT[modis_source]].fillna(0).astype("int64").to_numpy()
    out = merged[PAIRED_COLUMNS]
    return out.sort_values(KEYS, ignore_index=True)
