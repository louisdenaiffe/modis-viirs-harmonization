# Data contract v2: global harmonization

The goal is **any FIRMS files, anywhere on Earth, any years**. Typical inputs are per-country yearly
CSVs (`modis_2019_Brazil.csv`), FIRMS "all countries" zips, or global yearly files. Mixed countries,
years and sensors can sit in the same `data_dir`, and their extents and dates do not have to match.

The code lives in `harmonize/`. Settings are in `harmonize.config.Config`, and constants
(`METRICS`, `DAYNIGHT`, `MODIS_CONFIGS`, source codes) are in `harmonize/config.py`. Nothing may
hard-code a country, a year, a region or a file name.

What changes from v1, and why:
1. **Coverage is spatial and daily.** v1 treated a month as covered if any point existed anywhere,
   and that breaks in two ways:
   - With MODIS Italy 2025 and VIIRS Greece 2025 in the same folder, Italy's MODIS fires get
     paired with VIIRS = 0.
   - A month that VIIRS only partly covers (VIIRS starts on 2012-01-20) gets compared against a
     full month of MODIS.
2. **The factor varies by region.** Italy's 2025 factor over-estimates Greece by 11-57 %
   depending on the metric. A single global ratio is now only the baseline.
3. **Global volumes.** About 10-30 M points per year. Process data file by file with compact
   dtypes, cache parsed files as parquet, and keep peak RAM under about 3 GB on the 1.4 GB test set.
4. **The MODIS platform mix changes over time.** Terra and Aqua are combined where both cover a
   tile-day, otherwise Terra-only or Aqua-only is used. The right factor is picked per tile-day.

## 0. Module ownership

| module | owner | public API |
|---|---|---|
| `config.py`, `pipeline.py` | integrator | `Config`; `python -m harmonize.pipeline` |
| `ingest.py` | A | `load_points(cfg, columns=None) -> DataFrame`, `apply_filters(points, cfg)`, `domain_from_filename(name) -> str` |
| `coverage.py` (new) | A | `build_coverage(points_all, cfg) -> DataFrame` (§2), `tag_points(points, coverage, cfg) -> DataFrame` (adds §2 columns) |
| `aggregate.py` | A | `aggregate(points, cfg, by_config=False) -> DataFrame` (§3), `make_paired(points_tagged, modis_source, cfg) -> DataFrame` (§4), `cell_id_for`, `period_for` |
| `harmonized.py` (new) | A | `build_harmonized(points_tagged, coef, cfg) -> DataFrame` (§6). Calls B's `apply_coefficients`. |
| `calibrate.py` | B | `MODELS`, `fit_model(name, paired, metric, cfg) -> dict`, `apply_model(params, modis_rows, metric) -> ndarray`, `fit_all(paired_by_source, cfg, training_meta=None) -> dict` (§5), `apply_coefficients(coef, metric, modis_rows, cfg=None, model=None) -> ndarray`, `stability_table(...)` |
| `validate.py`, `plots.py`, `METHOD.md` | C | §7 |
| `tests/` | each owner | `pytest -q` must stay green |

## 1. Point table (`load_points`)

These are the v1 columns, and they all stay:

`sensor, source, satellite_raw, latitude, longitude, datetime_utc, acq_date, acq_time, daynight,`
`bright_mir_k, bright_tir_k, frp, scan, track, confidence_raw, confidence_class, type, version,`
`source_file`

One new column:
- `domain` (category): `domain_from_filename(source_file)`. It removes the sensor token, the year
  token and the extension, so `modis_2019_Brazil.csv` and `viirs-snpp_2019_Brazil.csv` both become
  `Brazil`. If nothing recognisable is left, it is the file stem. Validation uses it only as a
  grouping label (leave-domain-out). Coverage does **not** use it.

dtypes: floats are float32. `latitude` and `longitude` are float64, because cell edges need the
precision. Strings with few distinct values are `category`. Accept `*.csv`, plus `*.zip`
containing CSVs, recursively under `data_dir`. Cache each parsed input in `cfg.cache_dir` as
parquet, keyed by absolute path, size and mtime.

`apply_filters`: same as v1 (types, confidence). It also deduplicates on `(source, latitude,
longitude, datetime_utc)`, because border points can appear in two country files.

## 2. Coverage

`build_coverage(points_all, cfg)` runs on **unfiltered** points, all types. It returns one row per
`(source_file, source, cov_tile)` with `date_min` and `date_max` (the first and last `acq_date`
of that file). `cov_tile = f"{iy}_{ix}"` at `cfg.coverage_tile_deg`, using the same formula as
cell_id. A file covers every tile its points touch, every day from `date_min` to `date_max`. If
several files of the same source cover a tile, the union of their date ranges is used.

`tag_points(points, coverage, cfg)` adds these columns to any points table:
- `cov_tile`
- `viirs_covered` (bool): `cfg.viirs_reference` covers this tile on this `acq_date`.
- `terra_covered`, `aqua_covered` (bool)
- `modis_config` (category): `MODIS_ALL` if Terra and Aqua both cover the tile-day, otherwise
  `MODIS_TERRA` or `MODIS_AQUA`, or `NONE`.

The tagging must be vectorized, for example a merge on `(source, cov_tile)` followed by date
comparisons, or interval logic. It must not loop over rows in Python.

## 3. Aggregated table (`aggregate`)

The table is long and sparse: only rows with `n_hotspots > 0`, one row per
`(source, cell_id, period, daynight)`. `source` takes the point sources plus `MODIS_ALL`
(Terra ∪ Aqua). `daynight` takes D, N, and ALL (= D ∪ N). These are as in v1.

Columns:
- `source, cell_id, cell_lat, cell_lon, period, period_start, daynight`
- `n_hotspots, fire_cell_days, frp_sum`: as in v1.
- New per-row features, from that source's points only, so they can be computed from MODIS alone
  in a back-cast year:
  - `frp_mean` (MW per detection)
  - `frp_p90` (90th percentile of FRP)
  - `scan_mean` (km, along-scan pixel size, which is a proxy for view angle)
  - `bright_mir_mean`
  - `n_terra`, `n_aqua` (detections from each platform; 0 for VIIRS)
- `domain`: the most common domain of the row's points.

`by_config=True` adds `modis_config` to the key. Used by §6.

## 4. Paired table (`make_paired(points_tagged, modis_source, cfg)`)

`modis_source` is `MODIS_ALL`, `MODIS_AQUA` or `MODIS_TERRA`. Keep only the points on tile-days
covered by **both** sides:
- `MODIS_ALL`: `modis_config == MODIS_ALL` and `viirs_covered`.
- `MODIS_AQUA`: `aqua_covered` and `viirs_covered`.
- `MODIS_TERRA`: `terra_covered` and `viirs_covered`.

For VIIRS points the same rule is evaluated with their own tile-date columns. Aggregate each side
(§3), then outer-join on `(cell_id, period, daynight)` and fill missing values with 0.

Columns:
- `cell_id, cell_lat, cell_lon, period, period_start, daynight, domain, modis_source`
- `modis_<m>`, `viirs_<m>` for each m in `n_hotspots, fire_cell_days, frp_sum`
- `modis_frp_mean, modis_frp_p90, modis_scan_mean, modis_bright_mir_mean, modis_n_terra, modis_n_aqua`
  (NaN where MODIS = 0)
- `viirs_frp_mean` (for information only, never used as a predictor)
- `n_days_covered`: number of jointly covered days in that cell's coverage tile and period. A
  partly covered month carries its true exposure.

## 5. Calibration (B)

**A model maps MODIS-side rows to VIIRS-equivalent values.** It may use region (via `cell_lat`
and `cell_lon`), season (via `period` and latitude), and MODIS-side features. It must never use
VIIRS columns at apply time. `apply_model(params, modis_rows, metric)` takes rows shaped like §3
MODIS rows (columns `cell_lat, cell_lon, period, daynight, <metric>, frp_mean, ...`) and returns
an ndarray of length `len(modis_rows)`, ≥ 0, with NaN-safe handling.

Required models:
- `ratio_global`: the v1 ratio of totals, y = k·x. This is the baseline.
- `ratio_regional`: k depends on the cell's position in nested tiles `cfg.region_levels_deg`,
  coarse to fine, with empirical-Bayes shrinkage of each tile's k toward its parent. A tile with
  little data (or none, such as a region never seen in training) falls back to its parent and
  ultimately to global.
- `glm_features`: a Poisson GLM on aggregated units (for example 5° tile × month × daynight). It
  fits log E[V] = log M + β·z, where z contains only MODIS-observable features such as log
  `frp_mean`, `scan_mean`, terra share, |lat|, a hemisphere-aware season and D/N. It transfers to
  unseen regions because it needs no lookup table.
- `glm_regional`: `glm_features` plus a shrunken regional residual.

B may add models. Every model's `params` must be JSON-serialisable and must fully define the
predictions. `k` is clipped to a sane range, stored in the params. `fire_cell_days` predictions
are capped at the number of days in the period.

**Coefficients JSON** (`calibration_coefficients.json`, `schema_version: 2`):

```json
{"schema_version": 2, "created_utc": "...", "config": {},
 "training_data": {"source_files": [], "domains": [], "periods": [], "years": []},
 "recommended": {"metric": "...", "model": "...", "reason": "..."},
 "coefficients": [{"metric": "...", "model": "...", "modis_source": "MODIS_ALL|MODIS_AQUA|MODIS_TERRA",
                   "daynight": "D|N|ALL", "params": {}, "n_train": 0}]}
```

`apply_coefficients(coef, metric, modis_rows, cfg=None, model=None)` dispatches each row on
`modis_rows["source"]`, which is the MODIS configuration, and on `daynight`. A missing D or N
entry falls back to ALL. A missing `MODIS_TERRA` or `MODIS_AQUA` entry falls back to `MODIS_ALL`
with a warning.

## 6. harmonized.csv (`build_harmonized`, A)

One row per `(cell_id, period, daynight)` for the recommended metric.

| column | meaning |
|---|---|
| `cell_id, cell_lat, cell_lon, period, daynight, domain, metric` | keys |
| `viirs_raw` | aggregate of VIIRS points (NaN if VIIRS covers none of this cell's tile-days in the period) |
| `modis_raw` | aggregate of all MODIS points (NaN if MODIS covers none) |
| `modis_as_viirs_equivalent` | Σ over MODIS configs of `apply_coefficients` on MODIS points from that config, all days |
| `harmonized_value` | `viirs_raw` (on VIIRS-covered days) + `apply_coefficients` on MODIS points from days **not** covered by VIIRS |
| `source_flag` | `VIIRS` (every MODIS-covered day is also VIIRS-covered), `MODIS_CALIBRATED` (no VIIRS-covered day), `MIXED` (partly covered period) |
| `viirs_days`, `modis_only_days` | days in the period covered by VIIRS, and days covered only by MODIS, in this cell's tile |

Notes:
- For `fire_cell_days`, summing over days with different configs is exact, because the days do not overlap.
- Cap `harmonized_value` for `fire_cell_days` at the number of days in the period.
- Write `harmonized.csv`, and `harmonized.parquet` too if there are more than 1 M rows.

## 7. Validation (C)

C imports only `MODELS`, `fit_model` and `apply_model` from B, and builds its own folds and scores.

Hold-out schemes:
- leave-one-domain-out (country)
- spatial blocks (10° tiles, grouped)
- leave-one-year-out, when at least 2 years are present
- leave-one-month-out (LOMO)

Scores for each metric × model × modis_source × daynight:
- per domain-year: bias of the annual total, R² and Spearman of the monthly totals
- the distribution of those across domains: median |bias|, 90th percentile |bias|, worst case
- the pooled global bias

Baselines: raw MODIS and `ratio_global`. The selection criterion is the 90th percentile of
|per-domain bias| under leave-one-domain-out, because transfer to unseen regions is the goal.
