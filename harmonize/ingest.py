"""Load FIRMS archive CSVs (MODIS C6.1 / VIIRS 375 m) into the SCHEMA §1 point table.

Every ``*.csv`` in ``cfg.data_dir`` is read; the sensor is detected from the columns,
never from the file name, so any country / year / satellite combination works.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import CONFIDENCE_ORDER, Config

POINT_COLUMNS = [
    "sensor", "source", "satellite_raw", "latitude", "longitude", "datetime_utc",
    "acq_date", "acq_time", "daynight", "bright_mir_k", "bright_tir_k", "frp",
    "scan", "track", "confidence_raw", "confidence_class", "type", "version",
    "source_file",
]

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

# columns that identify a detection (used for de-duplication across overlapping files)
DEDUP_COLUMNS = [c for c in POINT_COLUMNS if c != "source_file"]


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


def modis_confidence_class(conf: pd.Series, cfg: Config) -> pd.Series:
    c = pd.to_numeric(conf, errors="coerce")
    if c.isna().any():
        bad = conf[c.isna()].unique()[:5]
        raise ValueError(f"Non-numeric MODIS confidence values: {list(bad)}")
    out = np.where(c <= cfg.modis_conf_low_max, "low",
                   np.where(c >= cfg.modis_conf_high_min, "high", "nominal"))
    return pd.Series(out, index=conf.index, dtype="str")


def viirs_confidence_class(conf: pd.Series) -> pd.Series:
    out = conf.astype(str).str.strip().str.lower().map(VIIRS_CONF)
    if out.isna().any():
        bad = conf[out.isna()].unique()[:5]
        raise ValueError(f"Unknown VIIRS confidence values: {list(bad)}")
    return out.astype("str")


def read_firms_csv(path: Path, cfg: Config) -> pd.DataFrame:
    """Read one FIRMS CSV and return it in the §1 point schema (unfiltered)."""
    path = Path(path)
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    raw.columns = [c.strip().lower() for c in raw.columns]
    sensor = detect_sensor(raw.columns)
    mir, tir = ("brightness", "bright_t31") if sensor == "MODIS" else ("bright_ti4", "bright_ti5")

    sat = raw["satellite"].astype(str).str.strip()
    source = sat.str.upper().map(SATELLITE_TO_SOURCE)
    if source.isna().any():
        raise ValueError(f"{path.name}: unknown satellite values {list(sat[source.isna()].unique()[:5])}")
    if not source.str.startswith(sensor).all():
        raise ValueError(f"{path.name}: satellite values inconsistent with sensor {sensor}")

    acq_date = raw["acq_date"].astype(str).str.strip()
    hhmm = parse_acq_time(raw["acq_time"])
    dt = pd.to_datetime(acq_date + " " + hhmm, format="%Y-%m-%d %H%M", utc=True).astype(
        "datetime64[ns, UTC]")

    conf_raw = raw["confidence"].astype(str).str.strip()
    conf_class = (modis_confidence_class(conf_raw, cfg) if sensor == "MODIS"
                  else viirs_confidence_class(conf_raw))

    num = lambda col: pd.to_numeric(raw[col], errors="coerce").astype("float64")  # noqa: E731
    if "type" in raw.columns:
        ftype = pd.to_numeric(raw["type"].replace("", "0"), errors="coerce").fillna(0).astype("int64")
    else:
        ftype = pd.Series(0, index=raw.index, dtype="int64")

    out = pd.DataFrame({
        "sensor": pd.Series(sensor, index=raw.index, dtype="str"),
        "source": source.astype("str"),
        "satellite_raw": sat.astype("str"),
        "latitude": num("latitude"),
        "longitude": num("longitude"),
        "datetime_utc": dt,
        "acq_date": acq_date.astype("str"),
        "acq_time": hhmm.astype("int64"),
        "daynight": raw["daynight"].astype(str).str.strip().str.upper().astype("str"),
        "bright_mir_k": num(mir),
        "bright_tir_k": num(tir),
        "frp": num("frp"),
        "scan": num("scan"),
        "track": num("track"),
        "confidence_raw": conf_raw.astype("str"),
        "confidence_class": conf_class,
        "type": ftype,
        "version": (raw["version"] if "version" in raw.columns
                    else pd.Series("", index=raw.index)).astype(str).str.strip().astype("str"),
        "source_file": pd.Series(path.name, index=raw.index, dtype="str"),
    })
    return out[POINT_COLUMNS]


def load_points(cfg: Config) -> pd.DataFrame:
    """All ``*.csv`` in ``cfg.data_dir`` -> unfiltered point table (SCHEMA §1).

    Not de-duplicated (``apply_filters`` does that) so that coverage can be
    computed from the raw table.
    """
    files = sorted(Path(cfg.data_dir).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No *.csv files in {cfg.data_dir}")
    frames = [read_firms_csv(f, cfg) for f in files]
    frames = [f for f in frames if len(f)]
    if not frames:
        return read_firms_csv(files[0], cfg)
    return pd.concat(frames, ignore_index=True)


def apply_filters(points: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Keep ``type in cfg.keep_types`` and ``confidence_class >= cfg.min_confidence``;
    drop exact duplicate detections (all columns except ``source_file``) from overlapping files."""
    rank = points["confidence_class"].map(CONFIDENCE_ORDER)
    keep = points["type"].isin(cfg.keep_types) & (rank >= CONFIDENCE_ORDER[cfg.min_confidence])
    out = points.loc[keep]
    out = out.drop_duplicates(subset=DEDUP_COLUMNS, keep="first")
    return out.reset_index(drop=True)
