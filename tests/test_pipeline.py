import numpy as np
import pandas as pd

from harmonize.config import Config
from harmonize.pipeline import build_harmonized


def _agg():
    rows = [
        # overlap month: both sensors; cell B only seen by VIIRS
        ("MODIS_ALL", "A", "2025-07", "ALL", 2), ("VIIRS_SNPP", "A", "2025-07", "ALL", 7),
        ("VIIRS_SNPP", "B", "2025-07", "ALL", 3),
        # MODIS-only month (back-cast); large value to trigger the days-in-month cap
        ("MODIS_ALL", "A", "2005-02", "ALL", 20),
    ]
    a = pd.DataFrame(rows, columns=["source", "cell_id", "period", "daynight", "fire_cell_days"])
    a["cell_lat"], a["cell_lon"] = 45.125, 10.125
    return a


def test_build_harmonized_flags_zero_fill_and_cap():
    coef = {
        "config": Config().to_dict(),
        "recommended": {"metric": "fire_cell_days", "model": "ratio", "modis_source": "MODIS_ALL",
                        "fit_level": "cell_period"},
        "coefficients": [{"metric": "fire_cell_days", "model": "ratio", "modis_source": "MODIS_ALL",
                          "daynight": "ALL", "fit_level": "cell_period",
                          "params": {"model": "ratio", "k": 3.0}, "n_train": 100}],
    }
    cov = {"MODIS_ALL": {"2025-07", "2005-02"}, "VIIRS_SNPP": {"2025-07"}}
    h = build_harmonized(_agg(), cov, coef, Config()).set_index(["cell_id", "period"])

    a = h.loc[("A", "2025-07")]
    assert a.source_flag == "VIIRS" and a.harmonized_value == 7 and a.modis_as_viirs_equivalent == 6
    b = h.loc[("B", "2025-07")]
    assert b.modis_raw == 0 and b.harmonized_value == 3          # zero-filled, VIIRS wins
    old = h.loc[("A", "2005-02")]
    assert old.source_flag == "MODIS_CALIBRATED" and np.isnan(old.viirs_raw)
    assert old.harmonized_value == 28                             # 20*3=60 capped at 28 days (Feb 2005)
