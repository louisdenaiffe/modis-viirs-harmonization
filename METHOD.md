# Harmonizing MODIS and VIIRS active-fire hotspots worldwide: method (v2)

NASA Space Apps prototype. The contract is `SCHEMA.md` (v2) and every setting is in
`harmonize/config.py`. The numbers below come from the development test set: **12 countries,
2019 and 2023**, 0.25° × month (`outputs_global_dev/paired.parquet`, 2.97 M paired rows).
They were produced by `harmonize/validate.py`, which is independent of the fitting code.

**Bottom line.**
- Harmonize **FRP sum** (fire radiative power, MW, summed per 0.25° cell and month) with
  `glm_regional`: a Poisson GLM on MODIS-side fire characteristics, times a shrunken
  regional correction. Terra + Aqua, day and night pooled.
- **Unseen countries** (leave-one-country-out, 24 country-years): the annual total is within
  **±20 %** for every country-year, the median |bias| is 5.8 % and the p90 is **13.1 %**.
- **Unseen years in seen regions** (leave-one-year-out, the real back-cast situation): the
  p90 is **9.8 %**.
- The v1 approach, one global ratio, gets a p90 of 48 % on FRP and 29 % on hotspot counts.
  Raw MODIS gets 75 %.
- **Why the regional variant.** It ties the feature-only GLM on unseen countries (13.1 % vs
  13.1 %), because in an unseen region the regional correction shrinks to zero. It is clearly
  better on unseen years (9.8 % vs 13.6 %).
- **Why that matters.** A production calibration on the global 2012-2024 overlap leaves no
  region unseen, so the back-cast is the leave-one-year-out case. The pipeline encodes this
  as its selection rule (`pipeline.choose_recommendation`): best p90 on leave-one-country-out,
  tie-break on leave-one-year-out.
- **Runner-up:** fire cell-days with `glm_regional` (p90 17.6 % on unseen countries, 10.9 % on
  unseen years).
- **End-to-end back-cast check:** calibrate on 2023, give the pipeline 2019 MODIS only, and
  compare with the 2019 VIIRS it never saw. See §6, "End-to-end back-cast".

## 1. Goal

Build one fire-activity series in **VIIRS-equivalent units** for any place on Earth and any
year:
- VIIRS S-NPP (375 m, from 2012-01-20) where it exists;
- MODIS Terra (from 2000-11) and Aqua (from 2002-07), both 1 km, converted to "what VIIRS
  would have seen" everywhere else. This means the 2000-2011 back-cast, plus any tile-day
  that VIIRS does not cover.

v1 was calibrated on Italy 2025 alone. Its single factor over-estimated Greece by 11-57 %,
which is why v2 treats the factor as something that may vary with region and fire regime,
and validates it by **transfer to countries the model has never seen**.

## 2. Data and coverage semantics

**Inputs.** Any FIRMS archive CSV or zip under `data_dir`: per-country yearly files, "all
countries" zips, or global files. Mixed sensors, countries and years are allowed, and their
extents and dates may differ. `domain` is the file label without the sensor and year tokens
(`modis_2019_Brazil.csv` → `Brazil`). It is used **only** as a grouping label for validation.

**Filtering** (unchanged from v1):
- keep `type == 0` (presumed vegetation fire);
- keep confidence ≥ nominal (MODIS 0-100 binned ≤ 29 / 30-79 / ≥ 80, matching VIIRS l/n/h);
- remove duplicates on (source, lat, lon, time), because a border point can appear in two
  country files.

**Coverage is spatial and daily** (SCHEMA §2). A file "covers" every 1° tile its points
(unfiltered, all types) touch, for every day between its first and last `acq_date`. A
sensor's coverage is the union over its files. Every point is then tagged with:
- `viirs_covered`, `terra_covered`, `aqua_covered` for its tile-day;
- `modis_config`: `MODIS_ALL` if Terra and Aqua both cover the tile-day, otherwise
  `MODIS_TERRA` or `MODIS_AQUA`.

This tagging fixes two failures of v1's "any point anywhere this month" rule:
- MODIS fires in a country that VIIRS files don't cover are no longer paired with VIIRS = 0.
- A partly covered month (for example VIIRS starting on 2012-01-20) is compared on its
  jointly covered days only. `n_days_covered` carries the true exposure.

A consequence is that a tile with no detection at all during a file's period is "not covered"
by that file. Such tiles carry no fire signal from either sensor, so this does not bias the
totals.

**Paired table** (SCHEMA §4). For each MODIS configuration (`MODIS_ALL`, `MODIS_AQUA`,
`MODIS_TERRA`), the table keeps the points on tile-days covered by both that configuration
and VIIRS. Each side is aggregated to 0.25° cell × month × {D, N, ALL}, and the two sides are
outer-joined and zero-filled. MODIS-side features come with every row: `frp_mean`,
`frp_p90`, `scan_mean` (a view-angle proxy), `bright_mir_mean` and the Terra/Aqua split.

**MODIS configurations.** Terra (10:30/22:30 local) and Aqua (13:30/01:30) see different
phases of the diurnal fire cycle. Aqua is close to S-NPP's 13:30 crossing. A factor is
therefore fitted per configuration, and at apply time it is chosen per tile-day: Terra-only
before July 2002, both after. A `MODIS_ALL` factor applied to Terra-only data would
under-count by roughly 2×.

## 3. Metrics

| metric | meaning | sensitivity |
|---|---|---|
| `n_hotspots` | detections | proportional to pixel area (375 m vs 1 km), so it depends on fire size |
| `fire_cell_days` | days with ≥ 1 detection in the 0.25° cell | less sensitive to pixel size; saturates at the number of days in the month |
| `frp_sum` | summed fire radiative power [MW] | physical, but MODIS misses low-FRP pixels and VIIRS I4 saturates on hot ones |

## 4. Models (`harmonize/calibrate.py`, owner B)

Every model is multiplicative per row: VIIRS-equivalent = k_row × MODIS_row, with k clipped
to [0.05, 100]. Predictions use MODIS-side columns only. The `fire_cell_days` predictions are
capped at the number of days in the period.

| model | k_row | transfers to an unseen region by |
|---|---|---|
| `ratio_global` (baseline) | Σ VIIRS / Σ MODIS | construction (one number) |
| `ratio_regional` | nested tiles of 40/20/10/5°, each tile's k shrunk toward its parent by empirical Bayes: k_t = (V_t + λ·k_parent)/(M_t + λ), with λ per level from an internal spatial CV | falling back to the parent tile, then to global |
| `glm_features` | log k = b0 + β·z, a Poisson GLM fitted on 5° × month units. z holds five MODIS-observable features: log density of the metric in the cell, log hotspots per fire-day, log `frp_mean`, `scan_mean` (view angle) and Terra share. \|lat\| and a hemisphere-aware season are implemented but switched off, because they made transfer to unseen countries worse (cell-days p90 0.19 → 0.23) | features: no lookup table |
| `glm_regional` | `glm_features` × a shrunken regional residual | features plus the parent-tile residual |

All models fit totals on aggregated units. The VIIRS mass seen in cells where MODIS saw
nothing is folded into the MODIS-positive cells. Without that, a back-cast would lose it:
in a year without VIIRS, those cells do not exist.

## 5. Validation design (`harmonize/validate.py`, owner C)

Only `MODELS`, `fit_model` and `apply_model` are imported from the calibration module.
Folds, out-of-fold (OOF) predictions and scores are computed independently. B's fit
statistics and recommendation are never read.

| scheme | folds | tests |
|---|---|---|
| **leave-one-domain-out** (primary) | one per country | transfer to a region never seen in training, which is the global use case |
| spatial blocks | 10° × 10° blocks, 5 size-balanced grouped folds | transfer across space, ignoring borders |
| leave-one-year-out | one per year (needs ≥ 2 years) | transfer in time: fire regime, orbit drift |
| LOMO | one per calendar month, all years and countries | seasonal transfer: a held-out July is never seen in any year |

Every scheme predicts each row exactly once. `tests/test_validate.py` checks the partition
and checks that no domain, year, block or month appears on both sides of any fold.

**Back-cast evaluation mode.** A model is applied only where the MODIS metric is > 0, and
predicts 0 elsewhere. Its OOF predictions are compared with **all** VIIRS, including
VIIRS-only cells.

**Scores**, for each metric × model × MODIS configuration × D/N/ALL:
- per domain-year: bias of the annual total, plus R² and Spearman of the 12 monthly totals;
- across the 24 domain-years: median, 90th percentile and maximum |bias|, and the pooled
  global bias.

R² is 1 − SS_res/SS_tot and can be negative. Bias in % is scale-free, so the same criterion
ranks metrics as well as models.

**Selection criterion:** the p90 of |domain-year bias| under leave-one-domain-out (ties go
to the worst case, then the median monthly R²). The baselines are raw MODIS and
`ratio_global`.

Outputs in `<out_dir>/validation/`:
- `scores.csv`: the distribution per scheme × combo;
- `domain_scores.csv`: per domain-year;
- `monthly_oof.csv`: OOF monthly totals per domain-year, with VIIRS and raw MODIS;
- `folds.csv`: train/test sizes and test domains per fold;
- `summary.csv`: the ranking.

Run time on the 3 M-row test set is about 2 min per (configuration, D/N) table with all four
models, 14 min in total for 3 configurations × D/N/ALL, at a peak of 1.8 GB RSS. Nothing is subsampled.

## 6. Results

Numbers come from the final pipeline run, `python -m harmonize.pipeline --data-dir data_global
--out-dir outputs_global`. It covers 48 files, 17.5 M raw points, 15.3 M after filters and
1.0 M paired cell-months for Terra + Aqua, and took 14 min with a 4.5 GB peak. Some tables
below were produced on the development copy of the same data (`outputs_global_dev/paired.parquet`)
and can differ by a few tenths of a point. The data are: 12 countries (Australia, Bolivia,
Brazil, Canada, Greece, India, Indonesia, Italy, Kazakhstan, Mexico, United States, Zambia),
2019 and 2023, 0.25° × month. The scores are out-of-fold, in back-cast mode, over 24
domain-years. They come from `outputs/validation/summary.csv` and `scores.csv`.

### Leave-one-domain-out, MODIS Terra + Aqua, day + night (primary)

| metric | model | median \|bias\| | **p90 \|bias\|** | max \|bias\| (worst) | pooled bias | median R² monthly |
|---|---|---|---|---|---|---|
| frp_sum | glm_features | 5.8 % | 13.1 % | 20.4 % (United States-2023) | -0.4 % | 0.98 |
| frp_sum | glm_regional | 5.8 % | 13.1 % | 20.3 % (United States-2023) | -0.5 % | 0.98 |
| fire_cell_days | glm_regional | 6.2 % | 17.6 % | 27.9 % (India-2023) | -0.6 % | 0.95 |
| fire_cell_days | glm_features | 6.4 % | 18.3 % | 27.9 % (India-2023) | +0.2 % | 0.95 |
| n_hotspots | glm_features | 10.8 % | 25.4 % | 64.4 % (Greece-2023) | -0.3 % | 0.96 |
| n_hotspots | glm_regional | 10.6 % | 27.4 % | 64.4 % (Greece-2023) | -0.9 % | 0.96 |
| n_hotspots | ratio_global | 17.3 % | 28.6 % | 42.8 % (Greece-2023) | +0.3 % | 0.92 |
| n_hotspots | ratio_regional | 15.2 % | 30.6 % | 42.8 % (Greece-2023) | -0.6 % | 0.94 |
| fire_cell_days | ratio_global | 15.2 % | 34.1 % | 45.3 % (India-2023) | -3.6 % | 0.83 |
| fire_cell_days | ratio_regional | 14.2 % | 34.7 % | 45.3 % (India-2023) | -5.9 % | 0.82 |
| frp_sum | ratio_regional | 23.6 % | 47.8 % | 66.0 % (Canada-2019) | +2.7 % | 0.83 |
| frp_sum | ratio_global | 23.2 % | 47.9 % | 66.6 % (Canada-2019) | +2.5 % | 0.81 |
| fire_cell_days | raw_modis | 57.6 % | 68.8 % | 74.2 % (India-2023) | -55.9 % | 0.14 |
| frp_sum | raw_modis | 28.1 % | 75.3 % | 123.9 % (Greece-2023) | +35.6 % | 0.89 |
| n_hotspots | raw_modis | 74.4 % | 81.3 % | 82.9 % (Canada-2023) | -76.8 % | -0.01 |

Per-country annual FRP bias, in % (held-out country; rows above are p90 over these 24 values):

| country | glm_regional 2019 / 2023 | ratio_global 2019 / 2023 | raw MODIS 2019 / 2023 |
|---|---|---|---|
| Australia | +0 / -2 | +16 / +22 | +50 / +58 |
| Bolivia | -0 / +4 | -2 / -8 | +34 / +25 |
| Brazil | +1 / +8 | -16 / -19 | +19 / +14 |
| Canada | +6 / -10 | +67 / +42 | +109 / +78 |
| Greece | +11 / +11 | +2 / +65 | +39 / +124 |
| India | -9 / -14 | -43 / -48 | -21 / -28 |
| Indonesia | -5 / -9 | -29 / -48 | -2 / -28 |
| Italy | +11 / +2 | -36 / -24 | -14 / +3 |
| Kazakhstan | +8 / -3 | +25 / -3 | +70 / +32 |
| Mexico | +6 / +6 | -18 / -22 | +12 / +7 |
| United States | +17 / +20 | +16 / +2 | +56 / +38 |
| Zambia | +1 / -2 | -34 / -38 | -7 / -13 |

### End-to-end back-cast (calibrate on 2023, give the pipeline 2019 MODIS only)

This test exercises the real back-cast path, not a validation shortcut:
1. `python -m harmonize.pipeline --data-dir <2023 files>` fits the coefficients.
2. `python -m harmonize.pipeline --data-dir <2019 MODIS files only> --coefficients <json>`
   applies them. It sees no VIIRS at all, so every row is `MODIS_CALIBRATED`.
3. The result is compared with the 2019 VIIRS FRP, which the pipeline never saw.

The model is `frp_sum` / `glm_regional`.

| country | back-cast bias | raw MODIS bias | monthly R² |
|---|---|---|---|
| Australia | +2.7 % | +49.7 % | 0.98 |
| Bolivia | −3.2 % | +33.8 % | 1.00 |
| Brazil | −5.9 % | +18.8 % | 0.99 |
| Canada | +6.0 % | +108.4 % | 0.98 |
| Greece | +7.3 % | +36.3 % | 0.91 |
| India | −0.7 % | −21.0 % | 0.99 |
| Indonesia | +0.5 % | −2.5 % | 0.99 |
| Italy | +11.9 % | −13.8 % | 0.98 |
| Kazakhstan | +10.2 % | +69.7 % | 0.97 |
| Mexico | +1.6 % | +12.4 % | 1.00 |
| United States | +9.8 % | +55.7 % | 0.94 |
| Zambia | +3.5 % | −6.8 % | 1.00 |
| **all 12** | **+0.6 %** | | |

The calibration only has one other year to learn from, and the back-cast is still within
±12 % in every country.

### p90 |domain-year bias| by scheme (MODIS_ALL, day + night)

| metric / model | leave-domain-out | spatial 10° blocks | leave-year-out | LOMO |
|---|---|---|---|---|
| frp_sum / glm_features | 13.1 | 14.0 | 13.6 | 12.2 |
| frp_sum / glm_regional | 13.1 | 14.0 | 9.8 | 10.0 |
| fire_cell_days / glm_regional | 17.6 | 17.5 | 10.9 | 6.4 |
| fire_cell_days / glm_features | 18.3 | 17.5 | 17.5 | 16.7 |
| n_hotspots / glm_features | 25.4 | 23.8 | 21.7 | 22.7 |
| n_hotspots / glm_regional | 27.4 | 23.8 | 18.0 | 11.6 |
| n_hotspots / ratio_global | 28.6 | 26.3 | 27.7 | 26.2 |
| n_hotspots / ratio_regional | 30.6 | 26.3 | 19.9 | 9.5 |
| fire_cell_days / ratio_global | 34.1 | 32.4 | 32.5 | 32.2 |
| fire_cell_days / ratio_regional | 34.7 | 32.4 | 23.4 | 13.4 |
| frp_sum / ratio_regional | 47.8 | 47.9 | 35.4 | 24.6 |
| frp_sum / ratio_global | 47.9 | 47.9 | 44.3 | 47.1 |

Leave-domain-out is the hardest scheme for every combination. It is therefore the binding
criterion, and `worst_scheme_p90_abs_bias_pct` equals it.

### MODIS configuration and day/night

These are the best combinations under leave-domain-out, by p90:
- **Aqua only:** frp_sum / glm_regional 20.5 %; fire_cell_days / GLM 32 %; n_hotspots /
  GLM 34 %. The best Aqua ratio for hotspots is 42.7 %.
- **Terra only:** fire_cell_days / glm_regional 30.2 %; n_hotspots / ratio 46 %; FRP / GLM
  52 %, and FRP / ratio 92 %.
- **Day + night split, Terra + Aqua:** day-only is best at 21.5 % (FRP), night-only at
  37 % (FRP) and up to 59 % for hotspots.

### What we take from this

1. **The single factor does not transfer.** The global ratio is unbiased in the pooled
   total (+0.3 to +2.5 %), but individual countries are off by up to ±45-67 %. The VIIRS /
   MODIS ratio is a property of the fire regime:
   - small, cool agricultural and peat fires (India, Indonesia) need a larger k;
   - large, intense boreal crown fires (Canada) need a smaller one.

   `map_ratio_and_k.png` shows this structure.
2. **MODIS-side features carry that regime information; geography does not, out of region.**
   - `ratio_regional` and `glm_regional` win clearly when the region was seen (LOMO, and
     leave-year-out: hotspots 30 % → 10-20 %).
   - Under leave-domain-out they collapse back to the global ratio or GLM, because the
     nearest coarse tile of a new country holds another biome.
   - `glm_features` needs no lookup and keeps its skill. Our reading, not yet checked by
     feature ablation: mean FRP per detection and cell density tell the model whether MODIS
     is seeing a few big fires or the tip of many small ones.
3. **FRP becomes the best metric once the model knows the fire intensity.** It was the worst
   metric under a constant ratio (p90 48 %). The cause is saturation and detection-limit
   effects that depend on fire intensity, and `frp_mean` captures them.
4. **For hotspot counts the GLM does not help in the tail.** Greece 2023 (+65 %) is a
   single extreme fire season, dominated by the very large August 2023 fires. There, the
   features push k the wrong way: feature-only transfer is weakest for out-of-distribution
   extreme seasons.
5. **Pool day and night, and use Terra + Aqua when both are available.** Night-only and
   Terra-only factors transfer badly. Aqua-only is a good fallback for FRP (20.5 %).
6. **Seasonality is right with or without calibration** (monthly Spearman ≈ 0.98, even for
   raw MODIS). Calibration fixes the level, and with the GLM it also fixes the monthly shape
   (R² 0.98).

Figures in `outputs/plots/`: `domain_bias_lodo.png`, `monthly_by_domain_lodo.png`,
`map_ratio_and_k.png`, `scatter_modis_vs_viirs.png`.

## 7. Caveats on these numbers

- The model choice is made on the same scores it is reported with. With 15 candidate
  combinations, the winner's 13.1 % / 9.8 % are slightly optimistic. The feature set was
  also tuned on these 12 countries.
- The p90 over 24 domain-years is about the 3rd-worst value. Countries are weighted equally
  whatever their size, so Greece (about 40 k VIIRS detections per year) weighs as much as
  Brazil (about 7 M).

## 8. Limitations

- **Small test set.** 2 years and 12 countries. With 24 domain-years, the p90 is close to the
  3rd-worst value, so it is noisy. Large fire regimes are missing entirely:
  - boreal Siberia and the Russian Far East;
  - the Sahel and West/Central African savannas (the largest MODIS fire counts on Earth);
  - mainland Southeast Asia (agricultural and shifting-cultivation burning);
  - Argentina and the Chaco, the Middle East, and Europe outside Italy and Greece.

  Leave-one-domain-out only tests transfer between the regimes we have.
- **Orbit drift.** Terra has drifted to earlier crossings since about 2020, and Aqua since
  about 2022. 2023 MODIS therefore samples different times of the diurnal cycle than
  2002-2019 MODIS did. Leave-one-year-out with 2019 against 2023 partly measures this.
  Factors for the 2000-2011 back-cast should be fitted, or at least checked, on 2012-2019.
- **S-NPP only.** NOAA-20 (2018+) and NOAA-21 have a different orbit phase (about 50 min
  apart) and slightly different detection counts. They are not used as the reference, and an
  S-NPP to NOAA-20 offset would need its own calibration.
- **FRP.** MODIS misses low-FRP pixels and VIIRS I4 saturates. FRP sums are physically
  different quantities, and the FRP ratio swings the most between countries for the
  feature-free models.
- **Cell-level skill.** The model moves VIIRS-only mass onto cells MODIS saw. It cannot
  recreate the fires MODIS missed elsewhere. Use the output aggregated (regions, countries,
  ≥ 5° tiles × month), not for single 0.25° cells.
- **Coverage from detections.** Coverage is inferred from where a file has points. A country
  file therefore "covers" only the tiles where something burned during the year. Joint
  coverage is exact for fire-bearing tiles and silent elsewhere, which is harmless for totals.
- **Regional models.** A regional factor transfers well within a region seen in training but
  poorly to a new region whose nearest coarse tile holds a different biome (see §6).

## 9. Scaling to the full globe and to 2000-2024

1. **Data.** Download the FIRMS global yearly archives (MODIS C6.1 and VIIRS S-NPP 375 m,
   2012-2024) into `data_dir`. Ingest works file by file, with a parquet cache and compact
   dtypes. A global year is about 10-30 M points.
2. **Domains.** With global files the filename domain is meaningless (`Global`). Set the
   leave-domain-out unit to continents or ecoregions instead: country files from the FIRMS
   country split, or a `domain` column recomputed from a 30° tile or a biome map before
   validation. The 10° spatial-block scheme already works without any domain label.
3. **Validation cost.** The cost is linear in rows × folds × models. Twelve years of global
   overlap is about 20× the test set. Run `run_validation(..., sources=("MODIS_ALL",
   "MODIS_TERRA"), daynights=("ALL",))` first, then D/N only for the selected combination.
   Leave-one-year-out becomes the second key criterion, together with a check that k shows
   no trend across 2012-2024 (orbit drift).
4. **Back-cast 2000-2011.** Run the pipeline on MODIS-only data with
   `--coefficients calibration_coefficients.json`. `harmonized.py` applies the
   `MODIS_TERRA` factor on Terra-only tile-days (before 2002-07-04) and `MODIS_ALL` after.
   Every value is flagged `MODIS_CALIBRATED`. Use the out-of-fold p90 domain bias as the
   uncertainty band of a regional annual total.

## 10. How to rerun

```bash
.venv/bin/python -m harmonize.pipeline --data-dir data_global --out-dir outputs_global   # end to end
.venv/bin/python -m harmonize.validate outputs_global/paired.parquet outputs_global      # validation only
.venv/bin/python -m harmonize.plots outputs_global/paired.parquet outputs_global         # figures only
.venv/bin/python -m pytest -q
```

From Python: `run_validation(paired_by_source, cfg, models=None, schemes=SCHEMES,
metrics=METRICS, sources=MODIS_CONFIGS, daynights=DAYNIGHT)` returns the five tables and
writes them as CSVs. `make_plots(paired_by_source, harmonized_or_None, coef_or_None, cfg)`
writes `plots/*.png`. With no paired data (a MODIS-only back-cast run) it returns `[]`.

Figures:
- `map_ratio_and_k.png`: per-2° tile observed VIIRS/MODIS ratio, and the recommended
  model's effective k;
- `domain_bias_lodo.png`: per-domain-year bias under leave-one-domain-out, `ratio_global`
  against the best other model;
- `monthly_by_domain_lodo.png`: VIIRS, raw MODIS and out-of-fold calibrated series per
  country;
- `scatter_modis_vs_viirs.png`: cell-month density;
- `harmonized_series.png`: drawn when `harmonized.csv` is given.
