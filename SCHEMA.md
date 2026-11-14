# Data contract (fixed before parallel work — do not change without the integrator)

All code lives in the `harmonize/` package; configuration is `harmonize.config.Config`.
Constants (`METRICS`, `DAYNIGHT`, source codes) come from `harmonize/config.py`.
Nothing may hard-code a country, a year or a file name. Input = every `*.csv` in `cfg.data_dir`.

## 0. Module ownership and public functions

| module | owner | public API |
|---|---|---|
| `harmonize/config.py` | integrator | `Config`, constants |
| `harmonize/ingest.py` | A | `load_points(cfg) -> DataFrame` (§1, unfiltered), `apply_filters(points, cfg) -> DataFrame` |
| `harmonize/aggregate.py` | A | `aggregate(points, cfg) -> DataFrame` (§2), `make_paired(agg, modis_source, cfg) -> DataFrame` (§3), `cell_id_for(lat, lon, cell_size_deg)`, `period_for(datetime_utc, time_step)` |
| `harmonize/calibrate.py` | B | `MODELS`, `fit_model(name, x, y) -> dict`, `apply_model(params, x) -> ndarray`, `fit_all(paired_by_source, cfg) -> dict` (§4 JSON), `apply_coefficients(coef_json, metric, modis_source, daynight, x) -> ndarray` |
| `harmonize/validate.py` | C | hold-out evaluation, writes `outputs/validation/*.csv` |
| `harmonize/plots.py` | C | diagnostic PNGs into `outputs/plots/` |
| `harmonize/pipeline.py` | integrator | `python -m harmonize.pipeline` runs end to end |
| `tests/` | A (schema, aggregation), B/C may add | `pytest` |

## 1. Point table (output of `load_points`; written filtered as `outputs/hotspots_clean.csv`)

One row per FIRMS detection. Detect the sensor from the columns, not the file name
(MODIS has `brightness`/`bright_t31`; VIIRS has `bright_ti4`/`bright_ti5`).

| column | dtype | notes |
|---|---|---|
| `sensor` | str | `MODIS` or `VIIRS` |
| `source` | str | `MODIS_TERRA`, `MODIS_AQUA`, `VIIRS_SNPP`, `VIIRS_NOAA20`, `VIIRS_NOAA21` |
| `satellite_raw` | str | original `satellite` value (`Terra`, `Aqua`, `N`, `1`, `N20`, `2`, `N21`…) |
| `latitude`, `longitude` | float | |
| `datetime_utc` | datetime64[ns, UTC] | from `acq_date` + `acq_time`; `acq_time` is HHMM, may be int `136` or zero-padded string `"0136"` |
| `acq_date` | str `YYYY-MM-DD` | kept as given (UTC date) |
| `acq_time` | int | HHMM |
| `daynight` | str | `D` / `N` |
| `bright_mir_k` | float | MODIS `brightness` (21/22, ~4 µm) / VIIRS `bright_ti4` |
| `bright_tir_k` | float | MODIS `bright_t31` (~11 µm) / VIIRS `bright_ti5` |
| `frp` | float | MW |
| `scan`, `track` | float | pixel size km |
| `confidence_raw` | str | original value as string |
| `confidence_class` | str | `low` / `nominal` / `high`. MODIS: `<= cfg.modis_conf_low_max` low, `>= cfg.modis_conf_high_min` high, else nominal. VIIRS: `l`/`n`/`h` (case-insensitive) |
| `type` | int | FIRMS type (0 veg fire, 1 volcano, 2 static land, 3 offshore). Missing column (e.g. NRT files) -> 0 |
| `version` | str | |
| `source_file` | str | basename of the input CSV |

`apply_filters`: keep `type in cfg.keep_types` and `confidence_class >= cfg.min_confidence`
(ordering `config.CONFIDENCE_ORDER`). Drop exact duplicates across overlapping files.

## 2. Aggregated table (output of `aggregate`; written as `outputs/aggregated.csv`)

Long format, **sparse** (only rows with `n_hotspots > 0`), one row per
`(source, cell_id, period, daynight)`.

| column | dtype | notes |
|---|---|---|
| `source` | str | each point `source`, **plus** `MODIS_ALL` = Terra ∪ Aqua computed from the points (not by summing rows — matters for `fire_cell_days`) |
| `cell_id` | str | `f"{iy}_{ix}"`, `iy = floor((lat + 90) / size)`, `ix = floor((lon + 180) / size)` |
| `cell_lat`, `cell_lon` | float | cell **centre**: `-90 + (iy + 0.5) * size`, `-180 + (ix + 0.5) * size`, rounded to 6 dp |
| `period` | str | month: `YYYY-MM`; day: `YYYY-MM-DD` (UTC) |
| `period_start` | str `YYYY-MM-DD` | first day of the period |
| `daynight` | str | `D`, `N`, and `ALL` (= D ∪ N, computed from points, not summed) |
| `n_hotspots` | int | number of detections |
| `fire_cell_days` | int | number of distinct UTC dates with >= 1 detection in that cell/period/daynight/source (1 when time_step = day) |
| `frp_sum` | float | summed FRP, MW |

## 3. Paired table (output of `make_paired(agg, modis_source, cfg)`)

Wide, zero-filled join of one MODIS source against `cfg.viirs_reference`, on the **union**
of `(cell_id, period, daynight)` keys where either sensor has a row (a cell-period seen by
only one sensor gets 0 for the other). Restricted to periods that both sensors cover
(a period is "covered" by a source if that source has at least one point of any type in it,
i.e. coverage is computed before filtering — pass the coverage via the unfiltered points or
an attribute; A decides and documents).

Columns: `cell_id, cell_lat, cell_lon, period, period_start, daynight,`
`modis_n_hotspots, modis_fire_cell_days, modis_frp_sum,`
`viirs_n_hotspots, viirs_fire_cell_days, viirs_frp_sum`, plus `modis_source` (str).

## 4. Calibration coefficients JSON (`outputs/calibration_coefficients.json`)

```json
{
  "schema_version": 1,
  "created_utc": "...",
  "config": { ...Config.to_dict()... },
  "training_data": {"source_files": [...], "periods": ["2025-01", ...], "n_cells": 0},
  "recommended": {"metric": "fire_cell_days", "model": "loglog", "modis_source": "MODIS_ALL",
                  "fit_level": "cell_period", "reason": "..."},
  "coefficients": [
    {"metric": "n_hotspots", "model": "ratio", "modis_source": "MODIS_ALL", "daynight": "D",
     "fit_level": "cell_period", "params": {"k": 5.1}, "n_train": 1234,
     "fit_stats": {"r2_log": 0.0, "bias_pct": 0.0}}
  ]
}
```

Model `params` (B may add models; each must be fully described by `params` so it can be
applied on another year without refitting):
- `ratio`: `{"k"}` → `y = k * x`
- `loglog`: `{"a", "b", "offset", "smearing"}` → `y = max(0, smearing * exp(a) * (x + offset) ** b - offset)`

`apply_coefficients` looks up `(metric, model, modis_source, daynight)`; if the D/N entry is
missing it falls back to `daynight = "ALL"`. Coefficients are only valid for the
`cell_size_deg` / `time_step` recorded in `config` — warn on mismatch.

## 5. harmonized.csv (`outputs/harmonized.csv`, built by the integrator)

For the recommended metric (column `metric` added), one row per
`(cell_id, period, daynight)` in the union of MODIS_ALL and VIIRS keys:
`cell_id, cell_lat, cell_lon, period, daynight, metric, modis_raw, viirs_raw,`
`modis_as_viirs_equivalent, harmonized_value, source_flag`

- `source_flag = "VIIRS"` and `harmonized_value = viirs_raw` when the period is covered by VIIRS;
- `source_flag = "MODIS_CALIBRATED"` and `harmonized_value = modis_as_viirs_equivalent` otherwise (back-cast years).
- `viirs_raw` is NaN where VIIRS does not cover the period; `modis_raw` NaN where MODIS doesn't.

## Validation (C)

C imports only `fit_model` / `apply_model` (and the MODELS list) from B and runs its own
folds and metrics. C never reads `fit_stats` from the JSON.
