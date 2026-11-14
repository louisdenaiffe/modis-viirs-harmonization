"""Single source of configuration for the harmonization pipeline.

Every module takes a `Config`; nothing may hard-code a country, a year or a path.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Config:
    data_dir: Path = Path("data")
    out_dir: Path = Path("outputs")

    # --- filtering -------------------------------------------------------
    keep_types: tuple[int, ...] = (0,)          # FIRMS `type`; 0 = presumed vegetation fire
    min_confidence: str = "nominal"             # one of "low" | "nominal" | "high"; rows below are dropped
    modis_conf_low_max: int = 29                # MODIS confidence <= 29 -> low
    modis_conf_high_min: int = 80               # MODIS confidence >= 80 -> high (30-79 nominal)

    # --- aggregation -----------------------------------------------------
    cell_size_deg: float = 0.25
    time_step: str = "month"                    # "month" | "day"

    # --- coverage (where/when each sensor's files actually provide data) ---
    coverage_tile_deg: float = 1.0              # a file "covers" the tiles its points touch, over its date range

    # --- calibration -----------------------------------------------------
    viirs_reference: str = "VIIRS_SNPP"         # target source for "VIIRS-equivalent"
    min_pairs_for_split_fit: int = 30           # below this, a D/N-specific fit falls back to ALL
    region_levels_deg: tuple[float, ...] = (40.0, 20.0, 10.0, 5.0)  # nested tiles for regional factors, coarse -> fine

    # --- performance / io ------------------------------------------------
    cache_dir: Path = Path(".cache")            # per-input-file parquet cache (keyed by path, size, mtime)
    points_format: str = "parquet"              # cleaned point output: "parquet" | "csv" | "both"

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.out_dir = Path(self.out_dir)
        self.cache_dir = Path(self.cache_dir)
        self.keep_types = tuple(int(t) for t in self.keep_types)
        self.region_levels_deg = tuple(float(x) for x in self.region_levels_deg)
        if self.points_format not in ("parquet", "csv", "both"):
            raise ValueError("points_format must be parquet, csv or both")
        if self.time_step not in ("month", "day"):
            raise ValueError(f"time_step must be 'month' or 'day', got {self.time_step!r}")
        if self.min_confidence not in CONFIDENCE_ORDER:
            raise ValueError(f"min_confidence must be one of {list(CONFIDENCE_ORDER)}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data_dir"] = str(self.data_dir)
        d["out_dir"] = str(self.out_dir)
        d["cache_dir"] = str(self.cache_dir)
        d["keep_types"] = list(self.keep_types)
        d["region_levels_deg"] = list(self.region_levels_deg)
        return d


CONFIDENCE_ORDER = {"low": 0, "nominal": 1, "high": 2}

# Source codes used everywhere (points `source` column, aggregated `source` column, JSON).
SOURCES_MODIS = ("MODIS_TERRA", "MODIS_AQUA")
MODIS_ALL = "MODIS_ALL"                         # synthetic union of Terra + Aqua, built in aggregation
# A MODIS "configuration" is which MODIS platforms cover a given tile-day: both -> MODIS_ALL,
# one -> MODIS_TERRA / MODIS_AQUA (e.g. Terra-only before Aqua's first data on 2002-07-04).
MODIS_CONFIGS = (MODIS_ALL, "MODIS_TERRA", "MODIS_AQUA")
SOURCES_VIIRS = ("VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21")
METRICS = ("n_hotspots", "fire_cell_days", "frp_sum")
DAYNIGHT = ("D", "N", "ALL")
