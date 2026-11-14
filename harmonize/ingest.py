"""Load FIRMS active-fire files (MODIS C6.1 / VIIRS 375 m) into the SCHEMA §1 point table.

Every ``*.csv`` and every CSV member of every ``*.zip`` found recursively under
``cfg.data_dir`` is read. The sensor is detected from the columns, never from the file
name, so any country / year / satellite combination works. Each parsed input is cached
as parquet in ``cfg.cache_dir`` (key = absolute path + size + mtime + parser settings), so a
warm run only reads parquet.

Memory: floats are float32 (latitude / longitude float64), low-cardinality strings are
``category``; ``load_points(cfg, columns=[...])`` loads only the columns a caller needs.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import union_categoricals

from .config import CONFIDENCE_ORDER, Config

POINT_COLUMNS = [
    "sensor", "source", "satellite_raw", "latitude", "longitude", "datetime_utc",
    "acq_date", "acq_time", "daynight", "bright_mir_k", "bright_tir_k", "frp",
    "scan", "track", "confidence_raw", "confidence_class", "type", "version",
    "source_file", "domain",
]
CATEGORY_COLUMNS = ["sensor", "source", "satellite_raw", "acq_date", "daynight", "confidence_raw",
                    "confidence_class", "version", "source_file", "domain"]

# satellite value (upper-cased, stripped) -> source code
SATELLITE_TO_SOURCE = {
    "TERRA": "MODIS_TERRA", "T": "MODIS_TERRA",
    "AQUA": "MODIS_AQUA", "A": "MODIS_AQUA",
    "N": "VIIRS_SNPP", "NPP": "VIIRS_SNPP", "SNPP": "VIIRS_SNPP", "SUOMI NPP": "VIIRS_SNPP",
    "1": "VIIRS_NOAA20", "N20": "VIIRS_NOAA20", "NOAA-20": "VIIRS_NOAA20",
    "NOAA20": "VIIRS_NOAA20", "J1": "VIIRS_NOAA20",
    "2": "VIIRS_NOAA21", "N21": "VIIRS_NOAA21", "NOAA-21": "VIIRS_NOAA21",
    "NOAA21": "VIIRS_NOAA21", "J2": "VIIRS_NOAA21",
}

VIIRS_CONF = {"l": "low", "n": "nominal", "h": "high",
              "low": "low", "nominal": "nominal", "high": "high"}

# a detection is identified by these (border points appear in two country files)
DEDUP_COLUMNS = ["source", "latitude", "longitude", "datetime_utc"]

# bump when the parsed layout changes, so stale caches are ignored
PARSER_VERSION = 2

_FLOAT32 = {"brightness", "bright_t31", "bright_ti4", "bright_ti5", "frp", "scan", "track"}
_FLOAT64 = {"latitude", "longitude"}


# --------------------------------------------------------------------------- helpers
def detect_sensor(columns) -> str:
    cols = {c.strip().lower() for c in columns}
    if {"bright_ti4", "bright_ti5"} <= cols:
        return "VIIRS"
    if {"brightness", "bright_t31"} <= cols:
        return "MODIS"
    raise ValueError(f"Cannot detect sensor from columns {sorted(cols)}")


def parse_acq_time(s: pd.Series) -> pd.Series:
    """HHMM as int (136), float-ish string ("136.0") or padded string ("0136") -> "0136"."""
    s = s.astype(str).str.strip().str.split(".", n=1).str[0]
    return s.str.zfill(4)


_SENSOR_TOKENS = {
    "modis", "viirs", "viirs-snpp", "viirs-noaa20", "viirs-noaa21", "viirs-n20", "viirs-n21",
    "viirs-j1", "viirs-j2", "snpp", "suomi", "npp", "suomi-npp", "noaa20", "noaa-20", "noaa21",
    "noaa-21", "j1", "j2", "n20", "n21", "terra", "aqua", "c2", "c6", "c61", "c6.1", "fire",
    "archive", "nrt", "sp", "firms", "hotspots", "active", "ac",
}
_TOKEN_PATTERNS = [
    re.compile(r"^\d+$"),                       # years, download ids, "1" of C6_1
    re.compile(r"^\d+(h|d)$"),                  # 24h / 48h / 7d windows
    re.compile(r"^[a-z0-9]*v?-c\d+(\.\d+)?$"),  # M-C61, J1V-C2, SV-C2
]


def domain_from_filename(name) -> str:
    """Grouping label from a file name: drops sensor / product tokens, years, ids and the
    extension (``modis_2019_Brazil.csv`` -> ``Brazil``). Falls back to the file stem."""
    stem = Path(str(name)).name
    for ext in (".csv", ".zip", ".parquet", ".txt"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
    kept = [t for t in re.split(r"[_\s]+", stem)
            if t and t.lower() not in _SENSOR_TOKENS
            and not any(p.match(t.lower()) for p in _TOKEN_PATTERNS)]
    return "_".join(kept) if kept else stem


def _cat_map(cat: pd.Series, func) -> pd.Categorical:
    """Apply ``func`` (Index -> array-like) to the categories of ``cat``, re-coding the values.
    Unmapped (NaN) results become NaN values."""
    cat = cat.astype("category")
    cats = cat.cat.categories
    mapped = pd.Index(func(cats))
    new_cats = pd.Index(mapped.dropna().unique())
    code_map = np.append(new_cats.get_indexer(mapped), -1)   # -1 slot for NaN codes
    codes = cat.cat.codes.to_numpy()
    return pd.Categorical.from_codes(code_map[codes], categories=new_cats)


def _const_cat(value: str, n: int) -> pd.Categorical:
    return pd.Categorical.from_codes(np.zeros(n, dtype="int8"), categories=pd.Index([value]))


# --------------------------------------------------------------------------- parsing
def _read_one_csv(buf: bytes, display_name: str, cfg: Config) -> pd.DataFrame:
    hdr = pd.read_csv(io.BytesIO(buf), nrows=0).columns
    sensor = detect_sensor(hdr)
    dtype = {}
    for c in hdr:
        lc = c.strip().lower()
        dtype[c] = ("float64" if lc in _FLOAT64 else "float32" if lc in _FLOAT32 else "category")
    raw = pd.read_csv(io.BytesIO(buf), dtype=dtype)
    raw.columns = [c.strip().lower() for c in raw.columns]
    n = len(raw)
    mir, tir = ("brightness", "bright_t31") if sensor == "MODIS" else ("bright_ti4", "bright_ti5")
    strip = lambda cats: cats.astype(str).str.strip()  # noqa: E731

    sat = _cat_map(raw["satellite"], strip)
    source = _cat_map(pd.Series(sat), lambda c: c.str.upper().map(SATELLITE_TO_SOURCE))
    if pd.isna(source).any():
        bad = pd.Series(sat)[pd.isna(source)].unique()[:5]
        raise ValueError(f"{display_name}: unknown satellite values {list(bad)}")
    if n and not all(str(s).startswith(sensor) for s in source.categories):
        raise ValueError(f"{display_name}: satellite values inconsistent with sensor {sensor}")

    acq_date = _cat_map(raw["acq_date"], strip)
    if pd.isna(acq_date).any():
        raise ValueError(f"{display_name}: missing acq_date")
    date_ns = pd.to_datetime(acq_date.categories, format="%Y-%m-%d").to_numpy("datetime64[ns]")

    t = raw["acq_time"].astype("category")
    t_cats = parse_acq_time(pd.Series(t.cat.categories.astype(str))).astype("int64").to_numpy()
    acq_time = t_cats[t.cat.codes.to_numpy()] if n else np.zeros(0, "int64")
    minutes = (acq_time // 100) * 60 + acq_time % 100
    dt_vals = date_ns[acq_date.codes] + (minutes * 60_000_000_000).astype("timedelta64[ns]") \
        if n else np.zeros(0, "datetime64[ns]")
    dt = pd.DatetimeIndex(dt_vals).tz_localize("UTC").astype("datetime64[ns, UTC]")

    conf_raw = _cat_map(raw["confidence"], strip)
    if sensor == "MODIS":
        def cls(cats):
            c = pd.to_numeric(pd.Series(cats), errors="coerce")
            if c.isna().any():
                raise ValueError(f"Non-numeric MODIS confidence values: {list(cats[c.isna()][:5])}")
            return np.where(c <= cfg.modis_conf_low_max, "low",
                            np.where(c >= cfg.modis_conf_high_min, "high", "nominal"))
    else:
        def cls(cats):
            out = pd.Series(cats).str.lower().map(VIIRS_CONF)
            if out.isna().any():
                raise ValueError(f"Unknown VIIRS confidence values: {list(cats[out.isna()][:5])}")
            return out.to_numpy()
    if pd.isna(conf_raw).any():
        raise ValueError(f"{display_name}: missing confidence values")
    conf_class = _cat_map(pd.Series(conf_raw), cls)

    if "type" in raw.columns:
        tt = raw["type"].astype("category")
        tc = pd.to_numeric(pd.Series(tt.cat.categories.astype(str)).str.strip().replace("", "0"),
                           errors="coerce").fillna(0).astype("int8").to_numpy()
        codes = tt.cat.codes.to_numpy()
        ftype = np.where(codes >= 0, np.append(tc, 0)[codes], 0).astype("int8")
    else:
        ftype = np.zeros(n, dtype="int8")

    if "version" in raw.columns:
        v = raw["version"].astype("category")
        if v.isna().any():
            v = v.cat.add_categories([""]).fillna("")
        version = _cat_map(v, strip)
    else:
        version = _const_cat("", n)

    out = pd.DataFrame({
        "sensor": _const_cat(sensor, n),
        "source": source,
        "satellite_raw": sat,
        "latitude": raw["latitude"].to_numpy("float64"),
        "longitude": raw["longitude"].to_numpy("float64"),
        "datetime_utc": dt,
        "acq_date": acq_date,
        "acq_time": acq_time.astype("int16"),
        "daynight": _cat_map(raw["daynight"], lambda c: c.astype(str).str.strip().str.upper()),
        "bright_mir_k": raw[mir].to_numpy("float32"),
        "bright_tir_k": raw[tir].to_numpy("float32"),
        "frp": raw["frp"].to_numpy("float32"),
        "scan": raw["scan"].to_numpy("float32"),
        "track": raw["track"].to_numpy("float32"),
        "confidence_raw": conf_raw,
        "confidence_class": conf_class,
        "type": ftype,
        "version": version,
        "source_file": _const_cat(display_name, n),
        "domain": _const_cat(domain_from_filename(display_name), n),
    })
    for c in CATEGORY_COLUMNS:
        out[c] = out[c].astype("category")
    return out[POINT_COLUMNS]


def read_input(path: Path, cfg: Config, display_name: str | None = None) -> pd.DataFrame:
    """Parse one input (CSV, or ZIP of CSVs) into the §1 schema, unfiltered, uncached."""
    path = Path(path)
    name = display_name or path.name
    if path.suffix.lower() == ".zip":
        frames = []
        with zipfile.ZipFile(path) as zf:
            for m in sorted(zf.namelist()):
                if m.lower().endswith(".csv") and not m.startswith("__MACOSX"):
                    frames.append(_read_one_csv(zf.read(m), f"{name}/{m}", cfg))
        if not frames:
            raise ValueError(f"{path}: zip contains no CSV")
        return concat_points(frames)
    return _read_one_csv(path.read_bytes(), name, cfg)


def read_firms_csv(path: Path, cfg: Config) -> pd.DataFrame:  # v1 name, kept for callers
    return read_input(path, cfg)


# --------------------------------------------------------------------------- cache
def _cache_paths(path: Path, cfg: Config, display_name: str) -> tuple[Path, str]:
    ap = str(Path(path).resolve())
    st = os.stat(ap)
    pfx = hashlib.sha1(ap.encode()).hexdigest()[:12]
    key = hashlib.sha1(repr((ap, display_name, st.st_size, st.st_mtime_ns, PARSER_VERSION,
                             cfg.modis_conf_low_max, cfg.modis_conf_high_min)).encode()).hexdigest()[:16]
    return Path(cfg.cache_dir) / f"{pfx}_{key}.parquet", pfx


def _read_cache(cpath: Path, columns=None) -> pd.DataFrame:
    import pyarrow.parquet as pq
    table = pq.read_table(cpath, columns=list(columns) if columns else None)
    # self_destruct frees each Arrow buffer as soon as it is converted (no 2x peak)
    df = table.to_pandas(self_destruct=True, split_blocks=True)
    del table
    return df


def load_file(path: Path, cfg: Config, columns=None, display_name: str | None = None) -> pd.DataFrame:
    """One input -> point table, via the parquet cache."""
    name = display_name or Path(path).name
    cpath, pfx = _cache_paths(path, cfg, name)
    if cpath.exists():
        try:
            return _read_cache(cpath, columns)
        except Exception:  # corrupt / partial cache -> re-parse
            pass
    df = read_input(path, cfg, name)
    try:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        for old in cpath.parent.glob(f"{pfx}_*.parquet"):  # stale versions of this input
            old.unlink(missing_ok=True)
        tmp = cpath.with_suffix(f".tmp{os.getpid()}")
        df.to_parquet(tmp, index=False)
        os.replace(tmp, cpath)
    except OSError:
        pass
    return df[list(columns)] if columns else df


def list_inputs(data_dir) -> list[Path]:
    data_dir = Path(data_dir)
    return sorted(p for p in data_dir.rglob("*")
                  if p.is_file() and p.suffix.lower() in (".csv", ".zip"))


def concat_points(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concat point frames column by column (bounded peak memory), keeping categoricals
    categorical with the union of categories. The input frames are emptied."""
    frames = list(frames)
    if len(frames) == 1:
        return frames[0].reset_index(drop=True)
    cols = list(frames[0].columns)
    out = {}
    for c in cols:
        if isinstance(frames[0][c].dtype, pd.CategoricalDtype):
            out[c] = pd.Series(union_categoricals([f[c] for f in frames], sort_categories=False))
        else:
            out[c] = pd.concat([f[c] for f in frames], ignore_index=True)
        for f in frames:
            del f[c]
    return pd.DataFrame(out, copy=False)


def load_points(cfg: Config, columns=None) -> pd.DataFrame:
    """All inputs under ``cfg.data_dir`` -> unfiltered point table (SCHEMA §1).

    ``columns``: optional subset of ``POINT_COLUMNS`` to return (saves memory).
    Not de-duplicated (``apply_filters`` does that) so coverage sees the raw table.
    """
    if columns is not None:
        bad = [c for c in columns if c not in POINT_COLUMNS]
        if bad:
            raise ValueError(f"Unknown point columns {bad}")
        columns = [c for c in POINT_COLUMNS if c in set(columns)]
    data_dir = Path(cfg.data_dir)
    files = list_inputs(data_dir)
    if not files:
        raise FileNotFoundError(f"No *.csv / *.zip files under {data_dir}")
    frames = []
    for f in files:
        rel = f.relative_to(data_dir).as_posix()
        frames.append(load_file(f, cfg, columns=columns, display_name=rel))
    nonempty = [f for f in frames if len(f)]
    out = concat_points(nonempty or frames[:1])
    del frames, nonempty
    try:  # hand Arrow's cached allocations back to the OS
        import pyarrow as pa
        pa.default_memory_pool().release_unused()
    except Exception:
        pass
    return out


def apply_filters(points: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Keep ``type in cfg.keep_types`` and ``confidence_class >= cfg.min_confidence``;
    drop duplicate detections ``(source, latitude, longitude, datetime_utc)`` from overlapping
    files (the first file in sorted order wins)."""
    cc = points["confidence_class"]
    if isinstance(cc.dtype, pd.CategoricalDtype):
        ok_cls = [c for c in cc.cat.categories
                  if CONFIDENCE_ORDER.get(str(c), -1) >= CONFIDENCE_ORDER[cfg.min_confidence]]
        conf_ok = cc.isin(ok_cls).to_numpy()
    else:
        conf_ok = (cc.map(CONFIDENCE_ORDER) >= CONFIDENCE_ORDER[cfg.min_confidence]).to_numpy()
    keep = points["type"].isin(cfg.keep_types).to_numpy() & conf_ok
    keep &= ~_duplicated(points, keep)      # dedupe among kept rows, before copying the table
    return points.loc[keep].reset_index(drop=True)


_HASH_CHUNK = 2_000_000


def _duplicated(points: pd.DataFrame, among: np.ndarray | None = None) -> np.ndarray:
    """Exact ``duplicated(subset=DEDUP_COLUMNS, keep='first')`` restricted to rows ``among``,
    via a 64-bit hash pre-pass (the exact check only runs on hash collisions, so memory stays
    about one uint64 per row)."""
    n = len(points)
    rows = np.arange(n) if among is None else np.flatnonzero(among)
    out = np.zeros(n, bool)
    if len(rows) == 0:
        return out
    src = points["source"]
    sc = (src.cat.codes.to_numpy() if isinstance(src.dtype, pd.CategoricalDtype)
          else pd.factorize(src)[0])
    lat = points["latitude"].to_numpy("float64")
    lon = points["longitude"].to_numpy("float64")
    t = points["datetime_utc"].array
    t = t.asi8 if hasattr(t, "asi8") else pd.to_datetime(points["datetime_utc"], utc=True).array.asi8
    h = np.empty(len(rows), "uint64")
    with np.errstate(over="ignore"):
        for lo in range(0, len(rows), _HASH_CHUNK):
            r = rows[lo:lo + _HASH_CHUNK]
            x = lat[r].view("uint64") * np.uint64(0x9E3779B97F4A7C15)
            x ^= lon[r].view("uint64") * np.uint64(0xC2B2AE3D27D4EB4F) + (x << np.uint64(6)) + (x >> np.uint64(2))
            x ^= t[r].view("uint64") * np.uint64(0x165667B19E3779F9) + (x << np.uint64(6)) + (x >> np.uint64(2))
            x ^= sc[r].astype("uint64") * np.uint64(0x27D4EB2F165667C5) + (x << np.uint64(6)) + (x >> np.uint64(2))
            h[lo:lo + _HASH_CHUNK] = x
    cand = pd.Series(h, copy=False).duplicated(keep=False).to_numpy()
    del h
    if cand.any():
        ci = rows[cand]
        sub = points.iloc[ci][DEDUP_COLUMNS]
        out[ci] = sub.duplicated(keep="first").to_numpy()
    return out
