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

    # --- calibration -----------------------------------------------------
    viirs_reference: str = "VIIRS_SNPP"         # target source for "VIIRS-equivalent"
    min_pairs_for_split_fit: int = 30           # below this, a D/N-specific fit falls back to ALL

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.out_dir = Path(self.out_dir)
        self.keep_types = tuple(int(t) for t in self.keep_types)
        if self.time_step not in ("month", "day"):
            raise ValueError(f"time_step must be 'month' or 'day', got {self.time_step!r}")
        if self.min_confidence not in CONFIDENCE_ORDER:
            raise ValueError(f"min_confidence must be one of {list(CONFIDENCE_ORDER)}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data_dir"] = str(self.data_dir)
        d["out_dir"] = str(self.out_dir)
        d["keep_types"] = list(self.keep_types)
        return d


CONFIDENCE_ORDER = {"low": 0, "nominal": 1, "high": 2}

# Source codes used everywhere (points `source` column, aggregated `source` column, JSON).
SOURCES_MODIS = ("MODIS_TERRA", "MODIS_AQUA")
MODIS_ALL = "MODIS_ALL"                         # synthetic union of Terra + Aqua, built in aggregation
SOURCES_VIIRS = ("VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21")
METRICS = ("n_hotspots", "fire_cell_days", "frp_sum")
DAYNIGHT = ("D", "N", "ALL")
