# Harmonizing MODIS and VIIRS active-fire hotspots worldwide: method (v2, full recalibration)

NASA Space Apps prototype. The contract is `SCHEMA.md` (v2) and every setting is in
`harmonize/config.py`. The numbers below come from the **full recalibration: 236 FIRMS
countries, 2012-2024, 0.25° × month**, split into two regime-stratified halves A and B
(`splits/country_split.csv`). It holds 321 M raw points (270 M after filters) and 16.8 M
paired rows for Terra + Aqua (cell × month × D/N/ALL). Scores were produced by `harmonize/validate.py`
and `harmonize/crosstest.py`, which are independent of the fitting code. The earlier
12-country × 2019/2023 results are kept in Appendix A as the baseline.

**Bottom line.**
- **Recommended:** harmonize **fire cell-days** (days with ≥ 1 detection per 0.25° cell and
  month) with `glm_regional`, Terra + Aqua, day and night pooled. The pipeline's selection
  rule picked it, and it wins under every size filter except the 12 baseline countries alone.
  FRP sum with `glm_regional` is a statistical tie on unseen countries (p90 24.0 % vs 23.1 %)
  and loses on unseen years (17.5 % vs 14.4 %). The earlier recommendation was frp_sum.
- **Unseen countries** (10-fold grouped K-fold over countries; country-years with ≥ 10 000
  VIIRS detections, n = 963): median |annual bias| 7.5 %, **p90 23.1 %**, pooled bias +0.6 %.
- **Unseen years in seen countries** (leave-one-year-out, the real back-cast situation, same
  tier): **p90 14.4 %**.
- **Countries the model never saw, in the other half of the world** (cross-test A→B and
  B→A pooled, ≥ 10 000 tier): p90 24.4 % for cell-days and 23.7 % for FRP. This is the same
  level as the K-fold, so the K-fold is not optimistic.
- **Compared with the baseline, on the same 12 countries × 2019/2023:**
  - Unseen years improved: FRP 9.8 → 5.7 %, cell-days 10.9 → 8.5 %, hotspots 18.0 → 10.1 %.
  - Unseen countries stayed about the same: FRP 13.1 → 13.6 %, hotspots 27.4 → 21.2 %, but
    cell-days got worse (17.6 → 20.6 %).
  - Precision on a global scale is lower than the 12-country numbers suggested, because the
    world holds harder fire regimes (Mediterranean, agricultural, steppe; §6.6).
- **Small countries are noisy.** Over all 2 427 country-years, p90 is 62-86 % for every
  model. It is dominated by territories with a few dozen detections a year, where a handful
  of fires sets the annual total (`plots/bias_vs_size_kfold.png`). Those numbers are reported
  but should not be used to rank models.
- **Orbit drift** is visible after 2019: the Terra VIIRS/MODIS ratio rises (+2 to +5 %/yr) and
  the Aqua ratio falls (2023-2024). The two largely cancel for Terra + Aqua. Fitting on
  2012-2019 only does not back-cast 2012-2019 better under leave-one-year-out (§6.7), so all
  years are used.

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

**Many domains: grouped K-fold over countries.** With ~200 countries, one fold per country
is not affordable, so above `MAX_LODO_DOMAINS` (30) domains `leave_domain_out` is replaced by
`domain_kfold`. The countries go into `N_DOMAIN_FOLDS` = 10 folds balanced by fire volume
(VIIRS detections, day + night, all MODIS configurations together). A seeded shuffle breaks
ties, followed by a largest-first greedy fill (`validate.domain_fold_map`, seed
`DOMAIN_FOLD_SEED`). Every (configuration, D/N) table uses the same assignment. No country
is ever on both sides of a fold, and the selection rule reads `domain_kfold` where it used to
read `leave_domain_out`. `calibrate.stability_table` uses the same grouping, with its own
copy of the code so the two modules stay independent.

**Parallel folds.** `run_validation(..., n_jobs=N)` (CLI `--jobs N`, or `HARMONIZE_JOBS`)
fits the folds in forked worker processes. The workers share the paired table copy-on-write,
so it is never pickled. The result does not depend on `n_jobs` (tested).

## 6. Results: full recalibration (236 countries, 2012-2024)

### 6.1 Data, split and runs

- **Data.** FIRMS per-year all-country zips (`data/country/zips/{modis|viirs-snpp}_{YEAR}_all_countries.zip`),
  2012-2024, MODIS C6.1 + VIIRS S-NPP. They hold 236 country names for VIIRS and 233 for
  MODIS, and the names are identical across years. Portugal is `Portugal` and Russia is
  `Russian_Federation`; neither file is empty. `Marshall_Islands` is MODIS-only, so it has
  nothing to pair with and is not in the split.
- **Country table** (`splits/country_split.csv`, built by `scripts/country_stats.py` and
  `scripts/make_split.py`). Each country has:
  - a GFED basis region, assigned from its fire-weighted VIIRS centroid by lat/lon rules plus
    explicit overrides;
  - a fire regime (boreal, savanna, tropical_forest, agricultural, mediterranean, steppe),
    explicit for every country with ≥ ~1 000 type-0 VIIRS detections a year and a regional
    default for the rest;
  - its mean type-0 VIIRS detections per year;
  - its centroid latitude and longitude.
- **Split.** Within each regime, countries go by decreasing volume to the half with the
  smaller regime volume. Romania is pinned to B. Balance, in type-0 VIIRS detections per year:

  | regime | A | B | countries A / B |
  |---|---|---|---|
  | savanna | 6.05 M | 6.05 M | 38 / 31 |
  | tropical forest | 1.52 M | 1.52 M | 32 / 34 |
  | agricultural | 0.96 M | 0.96 M | 36 / 30 |
  | boreal | 1.12 M | 0.42 M | 1 / 10 |
  | steppe | 0.11 M | 0.02 M | 1 / 5 |
  | mediterranean | 0.050 M | 0.051 M | 9 / 9 |
  | **total** | **9.82 M** | **9.04 M** | 117 / 119 |

  Two regimes cannot be balanced with whole countries: boreal (Russia alone is 1.12 M against
  Canada plus the Nordic countries) and steppe (Kazakhstan alone). Several GFED regions fall
  in one half only: BOAS in A; BONA, TENA and nearly all of AUST in B. That makes the
  cross-test a strict test of transfer to unseen regions.
- **Runs** (16 vCPU, 125 GB RAM):

  | step | wall time | peak RSS |
  |---|---|---|
  | `--paired-only`, half A, 2019 only (measurement) | 38 s | 2.0 GB |
  | `--paired-only`, half A, 2012-2024 (165 M raw points) | 9 min 13 s | 29.4 GB |
  | `--paired-only`, half B, 2012-2024 (156 M raw points) | 9 min 01 s | 27.9 GB |
  | cross-test A→B and B→A (135 fits each, 8 workers) | 5 min 30 s each | 24.0 GB |
  | `--from-paired A B` (calibrate 40 min serial, validation 12 workers) | 2 h 20 min | 23.8 GB |
  | harmonized A / B with `--coefficients` | 11 min each | 27.8 / 25.2 GB |
  | back-cast, 31 countries × 2000-2011 MODIS | 3 min 30 s | 9.4 GB |

  The one-year measurement extrapolated to about 26 GB for a 13-year half, which fits in
  RAM, so each half ran as a single pass. Year-by-year processing is exact as well: the
  single-year A/2019 paired table equals the 2019 slice of the 13-year run, row for row
  (1 915 210 rows).

### 6.2 Cross-test: fit on one half, score the other

`harmonize/crosstest.py` fits every metric × model × MODIS configuration × D/N once on one
half, then applies it to the other half in back-cast mode, using validate.py's
per-country-year scores. MODIS Terra + Aqua, day + night, p90 |annual bias| in %:

| metric / model | all A→B / B→A | ≥ 10 k A→B / B→A / pooled | 12 baseline countries, 2019+2023, pooled |
|---|---|---|---|
| fire_cell_days / glm_regional | 59.3 / 67.6 | 22.4 / 26.1 / **24.4** | 22.4 |
| fire_cell_days / glm_features | 61.8 / 71.1 | 24.9 / 25.7 / 25.5 | 19.3 |
| frp_sum / glm_regional | 71.4 / 93.2 | 22.6 / 25.8 / **23.7** | **12.0** |
| frp_sum / glm_features | 72.9 / 93.8 | 24.2 / 27.7 / 26.1 | 13.3 |
| n_hotspots / glm_regional | 65.0 / 79.0 | 30.8 / 30.9 / 30.9 | 20.6 |
| n_hotspots / ratio_regional | 62.2 / 71.5 | 27.9 / 33.4 / 30.9 | 21.8 |
| n_hotspots / ratio_global | 64.1 / 73.9 | 29.8 / 37.0 / 34.3 | 27.8 |
| fire_cell_days / ratio_global | 61.0 / 71.7 | 35.7 / 39.4 / 37.1 | 33.8 |
| frp_sum / ratio_global | 71.8 / 77.8 | 44.6 / 48.9 / 46.3 | 57.4 |
| raw MODIS (cell-days / FRP / hotspots) | ≥ 77 | 71.8 / 50.5 / 82.7 (pooled) | 68.7 / 75.3 / 81.3 |

- Number of country-years: 1 272 (B scored) and 1 155 (A scored) in total, of which 532
  and 431 have ≥ 10 k detections.
- In the 12-country column, each country appears exactly once, scored from the half it is
  not in.
- **Transfer to never-seen countries works about as well in both directions.** At ≥ 10 k,
  cell-days and FRP with `glm_regional` stay within 22-26 % p90 either way. Pooled biases
  stay within ±1.1 %.
- On the 12 baseline countries the cross-test FRP p90 (12.0 %) is as good as the baseline's
  leave-one-country-out (13.1 %), although each model saw only half the world.
- Terra-only and Aqua-only cross-test results are in `crosstest/*/summary.csv`. They follow
  the same pattern as the full validation (§6.5).

### 6.3 Full validation (`--from-paired A B`)

Scheme `domain_kfold` (10 folds, unseen countries), MODIS Terra + Aqua, day + night:

| metric / model | all 2 427 country-years: median / p90 | ≥ 10 k (963): median / **p90** / max (worst) | pooled bias | median monthly R² |
|---|---|---|---|---|
| fire_cell_days / glm_regional | 13.5 / 62.8 | 7.5 / **23.1** / 85 (Iceland-2014) | +0.6 % | 0.97 |
| frp_sum / glm_regional | 14.3 / 80.9 | 7.9 / 24.0 / 100 (Iceland-2014) | +0.2 % | 0.97 |
| fire_cell_days / glm_features | 16.8 / 66.1 | 10.3 / 24.2 / 85 (Iceland-2014) | −0.2 % | 0.95 |
| frp_sum / glm_features | 16.4 / 86.2 | 9.4 / 26.4 / 100 (Iceland-2014) | +0.2 % | 0.96 |
| n_hotspots / glm_regional | 17.3 / 75.6 | 11.3 / 29.3 / 100 (Iceland-2014) | −0.2 % | 0.95 |
| n_hotspots / ratio_regional | 19.0 / 66.4 | 12.3 / 30.2 / 100 (Iceland-2014) | −1.6 % | 0.94 |
| fire_cell_days / ratio_regional | 21.0 / 62.2 | 11.8 / 33.9 / 98 (Mongolia-2014) | −6.3 % | 0.91 |
| n_hotspots / ratio_global | 21.5 / 69.0 | 15.5 / 34.7 / 100 (Iceland-2014) | +0.2 % | 0.92 |
| fire_cell_days / ratio_global | 25.7 / 66.3 | 15.6 / 37.1 / 82 (Libya-2017) | −5.7 % | 0.90 |
| frp_sum / ratio_regional | 23.4 / 71.8 | 14.8 / 41.0 / 100 (Iceland-2014) | +5.8 % | 0.91 |
| frp_sum / ratio_global | 29.1 / 74.7 | 22.2 / 46.3 / 115 (Chile-2017) | +0.3 % | 0.88 |
| raw MODIS: cell-days / FRP / hotspots | 66 / 27 / 77 (median) | p90 71.8 / 50.5 / 82.7 | −56 / +12 / −75 % | |

The pooled-bias and R² columns are for the ≥ 10 k tier; `validation/tiers.csv` has every
tier, scheme, configuration and D/N.

**p90 |annual bias| by scheme**, Terra + Aqua, day + night. Each cell gives the ≥ 10 k tier
first, then the 12 baseline countries × 2019/2023 (24 country-years, the baseline's own
set):

| metric / model | domain K-fold | spatial 10° blocks | leave-year-out | LOMO |
|---|---|---|---|---|
| fire_cell_days / glm_regional | 23.1 · 20.6 | 23.3 · 19.4 | **14.4 · 8.5** | 14.1 · 8.5 |
| frp_sum / glm_regional | 24.0 · **13.6** | 26.0 · 12.8 | 17.5 · **5.7** | 16.7 · 5.4 |
| fire_cell_days / glm_features | 24.2 · 21.1 | 23.3 · 19.4 | 23.5 · 19.1 | 23.6 · 19.3 |
| frp_sum / glm_features | 26.4 · 14.5 | 26.0 · 12.8 | 26.0 · 13.1 | 25.9 · 12.8 |
| n_hotspots / glm_regional | 29.3 · 21.2 | 33.2 · 24.4 | 20.6 · 10.1 | 20.9 · 11.2 |
| n_hotspots / ratio_regional | 30.2 · 25.4 | 34.3 · 28.7 | 22.2 · 11.1 | 22.5 · 11.9 |
| n_hotspots / ratio_global | 34.7 · 29.0 | 34.3 · 28.7 | 33.8 · 28.8 | 33.9 · 28.8 |
| fire_cell_days / ratio_global | 37.1 · 33.2 | 37.2 · 33.0 | 37.0 · 33.2 | 36.8 · 34.0 |
| frp_sum / ratio_global | 46.3 · 57.4 | 46.0 · 55.7 | 46.3 · 56.4 | 46.8 · 57.1 |

- Under spatial blocks the regional models equal their feature-only or global counterpart
  exactly. With a whole 10° block held out, the regional correction shrinks to zero. The
  baseline showed the same.
- Unseen countries (domain K-fold, spatial blocks) are the binding schemes. Unseen years
  (leave-year-out) and unseen months (LOMO) are much easier, but only for the regional
  models, which can use what they learnt about the country in other years.

**Selection.** `pipeline.choose_recommendation` uses the best p90 under domain K-fold over
all country-years, with leave-year-out p90 as the tie-break within 1 point:
- `fire_cell_days` / `ratio_regional` scores 62.2 and `fire_cell_days` / `glm_regional`
  62.8, so they are tied;
- leave-year-out decides: 59.3 % against 59.6 %, so the pick is
  **`fire_cell_days` / `glm_regional`**.

The same rule run on the ≥ 1 k and ≥ 10 k tiers gives the same pick: 23.1 against FRP's 24.0
at ≥ 10 k, tie-broken by leave-year-out 14.4 against 17.5. Only the 12-baseline-countries
subset would pick frp_sum. The rule was not changed.

### 6.4 Did precision improve?

Like-for-like comparison: the 12 baseline countries × 2019/2023, Terra + Aqua, day + night,
p90 |annual bias|.

| metric / model | baseline: leave-country-out | now: domain K-fold | now: cross-test (other half) | baseline: leave-year-out | now: leave-year-out |
|---|---|---|---|---|---|
| frp_sum / glm_regional | 13.1 | 13.6 | 12.0 | 9.8 | **5.7** |
| fire_cell_days / glm_regional | 17.6 | 20.6 | 22.4 | 10.9 | **8.5** |
| n_hotspots / glm_regional | 27.4 | **21.2** | 20.6 | 18.0 | **10.1** |
| n_hotspots / ratio_global | 28.6 | 29.0 | 27.8 | 27.7 | 28.8 |

- **Unseen years improved for every regional model.** FRP went from 9.8 to 5.7 %. This is
  the back-cast case: the final calibration has seen every country, in 12 other years
  instead of 1. The 2019 hold-out in leave-year-out mirrors the baseline's end-to-end 2019
  back-cast:
  - FRP / `glm_regional` is within ±6 % in all 12 countries (baseline: ±12 %): Australia
    −1.0, Bolivia −2.3, Brazil −1.3, Canada +4.5, Greece +1.0, India +0.4, Indonesia +2.5,
    Italy +5.5, Kazakhstan +5.9, Mexico +2.4, United States +1.4, Zambia +0.4 %.
  - Cell-days / `glm_regional`: within ±10.4 % (Kazakhstan +10.4, Indonesia −8.6, United
    States −7.4, the rest within ±6 %).
- **Unseen countries did not improve.**
  - FRP: 13.1 → 13.6 %.
  - Cell-days got worse: 17.6 → 20.6 %.
  - Hotspot counts improved: 27.4 → 21.2 %.

  More training countries did not make transfer to a new country better on these 12.
- **Worldwide, the honest numbers are wider.** Over the 963 country-years with ≥ 10 k
  detections, unseen-country p90 is 23-24 % (cell-days, FRP) and unseen-year p90 is
  14-17 %. The 12-country set under-represented the hard regimes (§6.6).
- **Romania 2021**, scored by the A→B cross-test (Romania is in B; the model was fitted on
  A only), with `glm_regional`:

  | metric | baseline (out of sample) | cross-test A→B | final validation, domain K-fold | leave-year-out |
  |---|---|---|---|---|
  | n_hotspots | +3 % | **−0.9 %** | −0.1 % | −3.5 % |
  | fire_cell_days | +6 % | **+2.6 %** | −1.5 % | −4.5 % |
  | frp_sum | +19 % | **+13.8 %** | +6.1 % | +2.8 % |

  All three improved on the baseline, even with the model fitted on the other half of the
  world.

### 6.5 MODIS configuration and day/night (domain K-fold, ≥ 10 k)

- **Aqua only:** frp_sum / glm_regional 23.1 % (day only 22.0 %), cell-days / glm_regional
  25.0 %. Aqua alone is as good as Terra + Aqua, and it is the fallback for tile-days without
  Terra.
- **Terra only:** the best is cell-days / glm_regional at 39.4 %. FRP and hotspots are worse,
  and Terra-only cell-days reach 21.5 % under leave-year-out on 2012-2019 (§6.7). The 2000-11 to
  2002-07 Terra-only back-cast is therefore about twice as uncertain as the Terra + Aqua
  years.
- **Night only:** 34-45 % for every configuration. Pool day and night.

### 6.6 The 10 worst country-years and their fire types

Recommended combination (cell-days / glm_regional, domain K-fold, Terra + Aqua, day + night).

**Over all country-years**, the worst ten are tiny territories with 1-88 VIIRS detections in
the year: Djibouti 2013/2015/2016, Vanuatu 2012, Réunion 2024, Guadeloupe 2021, Martinique
2014, Tonga 2013, Mayotte 2013 and the Falkland Islands 2021. Their biases run from +440 to
+2 700 %, on totals of 1-29 cell-days. That is sampling noise, not a calibration failure (see
`plots/bias_vs_size_kfold.png`).

**Among country-years with ≥ 10 k detections** (`validation/worst10_ge10k.csv`):

| country-year | regime label | VIIRS detections | bias | what burns |
|---|---|---|---|---|
| Iceland 2014 | boreal | 46 979 | −85 % | Holuhraun lava field: 78 % of detections at locations active > 30 days |
| Libya 2017 | agricultural | 13 425 | −78 % | gas flares: 84 % at persistent locations |
| Egypt 2020 | agricultural | 10 163 | −67 % | 46 % at persistent locations (flares, industry) |
| Egypt 2015 | agricultural | 11 634 | −61 % | as above |
| Iceland 2024 | boreal | 10 131 | −60 % | Reykjanes (Sundhnúkur) eruptions: centroid 63.9° N 22.4° W, peaks in Mar/Aug/Nov; 45 % persistent |
| Saudi Arabia 2018 | agricultural | 10 131 | −60 % | 23 % persistent; flares and small farm fires |
| Algeria 2018 | mediterranean | 12 439 | −54 % | 49 % at persistent locations (gas flares) |
| Saudi Arabia 2020 | agricultural | 11 107 | −53 % | as above |
| Saudi Arabia 2021 | agricultural | 10 275 | −50 % | as above |
| Algeria 2024 | mediterranean | 11 157 | −47 % | as above |

- Every one of them is under-predicted, and in every one a large share of the "fire"
  signal is a **non-vegetation hot source labelled `type 0`**:
  - lava;
  - gas flares that FIRMS' static-source mask does not catch in VIIRS.

  MODIS, at 1 km, misses most of these small, persistent sources, so no vegetation-fire
  calibration can recover them. For comparison, Zambia 2018 has 0 % and Romania 2021 1 % of
  detections at locations active more than 30 days a year.
- Excluding such persistent sources, for example by masking locations active more than N
  days a year, is a possible future filter. It was **not** applied, because it would change
  the data definition.
- **By regime** (≥ 10 k, p90 for cell-days / FRP, glm_regional):

  | regime | p90 cell-days | p90 FRP |
  |---|---|---|
  | savanna (n = 479) | 13.2 % | 15.4 % |
  | tropical forest (196) | 17.7 % | 24.4 % |
  | boreal (28) | 23.8 % | 30.4 % |
  | steppe (21) | 27.5 % | 16.3 % |
  | agricultural (193) | 29.9 % | 31.6 % |
  | mediterranean (46) | 40.3 % | 36.1 % |

  Savanna and tropical-forest countries carry most of the world's fire. The arid
  agricultural and Mediterranean countries of North Africa and the Middle East carry most of
  the error.

### 6.7 Orbit drift

`drift/drift_ratio.csv` and `plots/drift_ratio.png` show the yearly VIIRS/MODIS ratio, as the
median over the 57-73 countries with ≥ 1 000 MODIS detections in every year (so a shift in the
regional mix cannot pass for drift). Index: 2012-2019 mean = 1.

| ratio, median country | 2012-2019 trend | 2019-2024 trend | 2024 index |
|---|---|---|---|
| Terra, hotspots | −0.7 %/yr | **+3.0 %/yr** | 1.18 |
| Terra, FRP | −1.1 %/yr | **+4.8 %/yr** | 1.25 |
| Aqua, hotspots | +1.0 %/yr | **−2.7 %/yr** | 0.91 |
| Aqua, FRP | +0.5 %/yr | −1.4 %/yr | 0.94 |
| Terra + Aqua, hotspots | +0.4 %/yr | −0.4 %/yr | 0.98 |
| Terra + Aqua, cell-days | +0.9 %/yr | −1.1 %/yr | 0.95 |
| Terra + Aqua, FRP | +0.6 %/yr | +1.4 %/yr | 1.06 |

- After 2019 Terra (drifting to earlier morning crossings) sees relatively less fire, so
  VIIRS/MODIS rises. Aqua, drifting later into the afternoon from 2022, sees relatively
  more, so the ratio falls.
- For Terra + Aqua the two largely cancel: cell-days stay within ±10 % of the 2012-2019
  mean in every year.

**Does fitting on 2012-2019 only back-cast better?** For each held-out year 2012-2019 we fit
twice: (a) on every other year 2012-2024, and (b) on every other year 2012-2019 only. Both
are scored like validate.py (`drift/drift_lyo*.csv`). p90 |annual bias|, ≥ 10 k
country-years:

| configuration / metric / glm_regional | all years | 2012-2019 only |
|---|---|---|
| Terra + Aqua, cell-days | 12.5 | 12.0 |
| Terra + Aqua, FRP | 16.0 | 15.7 |
| Terra + Aqua, hotspots | 19.1 | 20.9 |
| Terra, cell-days | 21.5 | 22.1 |
| Terra, FRP | 55.4 | 53.6 |
| Terra, hotspots | 36.4 | 34.8 |
| Aqua, cell-days | 13.8 | 13.1 |
| Aqua, FRP | 15.0 | 15.5 |

The differences are 0.3-1.8 points with no consistent sign, which is within the noise. The
drifted years neither help nor hurt a pre-2020 back-cast measurably, so **the final
coefficients use all 2012-2024 years**. The drift is real for single platforms, and a
Terra-only factor fitted on 2020-2024 alone would be biased. It is diluted in a 13-year fit.

### 6.8 Harmonized output and back-cast

- **Harmonized halves.** Each half was re-run with
  `--coefficients outputs_full/calibration_coefficients.json --skip-validation`, with no
  refitting:
  - A: 8.49 M rows (VIIRS 8 456 158, MIXED 36 188, MODIS_CALIBRATED 2 458);
  - B: 8.73 M rows (VIIRS 8 689 810, MIXED 40 479, MODIS_CALIBRATED 3 800).

  The MIXED rows are almost all January 2012 (VIIRS starts on 2012-01-20: 33 338 of
  36 188 in A, 37 617 of 40 479 in B). The MODIS-calibrated rows are scattered cell-months,
  mostly in June and July, whose tile had no VIIRS coverage. The paired tables these runs rebuild are
  byte-identical to the `--paired-only` ones.
- **Back-cast.** MODIS-only 2000-2011 for 31 countries (2-3 per GFED region, both halves) gives
  5.60 M rows, all MODIS_CALIBRATED. Checks (`backcast/`):
  - **Terra-only periods use the MODIS_TERRA entries.** Before 2002-07-04, all 1 780 381
    filtered points are tagged `MODIS_TERRA` (0 MODIS_ALL); after it, 99.9 % are
    `MODIS_ALL`. For January 2000 to June 2002, the pipeline's harmonized total (2 902 139
    cell-days) equals the total recomputed with the MODIS_TERRA entries exactly. With those
    entries removed (fallback to MODIS_ALL) it would be 1 254 591, 2.3× lower. The effective
    k is 4.1-4.4 in the Terra-only years, 2.66 in 2002 and 2.09-2.20 from 2003.
  - **Continuity at 2011/2012.** The effective k (harmonized / raw MODIS) is 2.155 in 2011
    (calibrated MODIS) and 2.145 in 2012 (VIIRS). The annual totals of the 31 countries are
    1.89 M in 2011 and 1.95 M in 2012, with no step (`plots/backcast_series.png`).
  - **In-sample check, 2012-2024.** For these 31 countries the calibrated MODIS has median
    |annual bias| 4.6 % and p90 16.1 % against actual VIIRS. This is in sample: the
    coefficients were fitted on these years.
  - **2024:** calibrated MODIS is +6.5 % above VIIRS for the 31 countries together. This is
    the Aqua drift (§6.7) showing up.

### 6.9 What we take from this

1. **Fire cell-days and FRP with `glm_regional` are the two good products.** On ≥ 10 k
   country-years they are statistically tied on unseen countries (23-24 % p90). Cell-days
   are clearly better on unseen years (14.4 % vs 17.5 %), which is the back-cast case. A
   single global ratio is 37-46 %, and raw MODIS 50-83 %.
2. **The regional correction pays off once a country has been seen.** That is always true
   for the 2000-2011 back-cast, since every country is in the 2012-2024 calibration.
   `glm_regional` beats `glm_features` by 9 (cell-days), 9 (FRP) and 12 (hotspots) points
   under leave-year-out.
3. **Transfer to an unseen region is where the error is.** Cross-test and domain K-fold
   agree (23-26 %). Most of the tail comes from North Africa and the Middle East, where
   type-0 VIIRS includes non-vegetation sources.
4. **Report regional sums, not small countries.** Below ~1 000 detections a year, single
   fires dominate the annual total and the bias distribution.

## 7. Caveats on these numbers

- **The model choice is made on the same scores it is reported with.** With 15 candidate
  combinations the winner's numbers are slightly optimistic. The cross-test (§6.2) is the
  cleanest check: its models never saw the scored half, and it agrees with the K-fold to
  within about one point.
- **Countries are weighted equally whatever their size.** Over all country-years the p90 is
  set by tiny territories, so it is reported but not used to argue model quality. The size
  tiers filter on the observed VIIRS detections of the country-year (`scripts/tiers.py`),
  never on the prediction, so they cannot favour a model. Tiers are not part of the
  pipeline's selection rule. That rule still ranks on all country-years, and it gives the
  same pick as the ≥ 1 k and ≥ 10 k tiers.
- **The regime labels are judgement calls at country level** (`regime_source` in the split
  CSV says which ones are explicit). They drive only the split balance and the per-regime
  breakdown, not the models.
- **Border cells after processing in parts.** Concatenating the A and B paired tables is not
  quite one pass over the union, in two ways:
  - 83 134 cell-months (1.2 % of MODIS_ALL day+night rows, ~3 % of the fire mass) appear in
    both halves. A cell straddling a border between an A country and a B country becomes two
    partial rows, each with its own domain, instead of one. Totals are preserved.
  - A detection listed in two country files from different halves is counted twice, because
    the de-duplication runs within a half.

  Within a half, year-by-year processing is exact (§6.1). For different years it is exact
  as long as every source has a detection somewhere on the first and last day of each part,
  which holds for every half and year here (`coverage.parquet`: all sources span 2012-01-01
  to 2024-12-31, VIIRS from 2012-01-20). See §9.

## 8. Limitations

- **Non-vegetation hot sources.** Gas flares, industry and lava labelled `type 0` dominate
  the error tail (§6.6), because MODIS misses most of them. A persistence mask (locations
  active on more than N days a year) would remove much of this, but it is a change to the
  data definition and has not been made.
- **Terra-only years.** The 2000-11 to 2002-07 back-cast relies on Terra-only factors.
  These transfer far worse than Terra + Aqua (domain K-fold p90 39 % for cell-days, ≥ 50 %
  for FRP) and Terra drifts after 2019 (§6.7). Treat 2000-2002 as roughly twice as
  uncertain.
- **Orbit drift.** It is not modelled. In a 13-year fit it is diluted, and the 2012-2019-only
  test shows no gain. Calibrated MODIS for 2024 is +6.5 % above VIIRS for the 31 back-cast
  countries, which is consistent with Aqua's drift.
- **S-NPP only.** NOAA-20 (2018+) and NOAA-21 are not used as the reference.
- **FRP.** MODIS misses low-FRP pixels and VIIRS I4 saturates, so FRP sums are physically
  different quantities. The GLM learns the mapping, but feature-free FRP ratios transfer
  badly (46 % p90).
- **Cell-level skill.** The model moves VIIRS-only mass onto cells MODIS saw, so use the
  output aggregated (regions, countries, ≥ 5° tiles × month), not single 0.25° cells.
- **Coverage from detections.** A file "covers" only tiles where something burned during its
  period. This is exact for fire-bearing tiles and silent elsewhere, which is harmless for
  totals.
- **Small countries.** Below ~1 000 VIIRS detections a year, an annual country total is
  dominated by a few fires: p90 |bias| is above 30 % even when the calibration is right on
  average.

## 9. Running at global scale: processing in parts

1. **Download** the per-year all-country zips and extract per-country CSVs into one folder
   per half and year: `scripts/country_stats.py`, `scripts/make_split.py`,
   `scripts/extract_halves.py`. 2012-2024 is 6.2 GB zipped and ~25 GB unpacked, and the
   parquet cache adds ~7 GB.
2. **Pair each part**: `--paired-only` runs ingest → coverage → filter → tag → pair, then
   writes `paired.parquet` and `coverage.parquet` and stops. A 13-year half needs ~30 GB RAM
   and 9 min. If RAM is short, run one year per part. The result is identical.
3. **Calibrate and validate on the union**: `--from-paired p1.parquet p2.parquet ...`
   concatenates the parts and runs the same calibration and validation as a single pass.
   This is tested: the parts give the same paired rows and the same coefficients as one run
   over the union. Mind the border caveat in §7.
4. **Cross-test**: `python -m harmonize.crosstest --train A --test B`.
5. **Harmonize or back-cast** any part without refitting:
   `--data-dir <part> --coefficients calibration_coefficients.json --skip-validation`.
   `harmonized.py` applies the `MODIS_TERRA` entries on Terra-only tile-days (before
   2002-07-04) and `MODIS_ALL` after. Every back-cast value is flagged `MODIS_CALIBRATED`.
   Use the out-of-fold p90 domain bias of the matching size tier as the uncertainty band of
   a country-year total.

## 10. How to rerun

```bash
# full recalibration (see §9); data_A/, data_B/, data_backcast/, runs/ are gitignored
python scripts/country_stats.py data_raw/zips data_raw/country_stats.csv
python scripts/make_split.py data_raw/country_stats.csv splits/country_split.csv
python scripts/extract_halves.py data_raw/zips splits/country_split.csv .
for h in A B; do python -m harmonize.pipeline --data-dir data_$h --out-dir runs/paired/$h/all --paired-only; done
PA=runs/paired/A/all/paired.parquet; PB=runs/paired/B/all/paired.parquet
python -m harmonize.crosstest --train $PA --test $PB --out outputs_full/crosstest/A_to_B --label A_to_B --jobs 8
python -m harmonize.crosstest --train $PB --test $PA --out outputs_full/crosstest/B_to_A --label B_to_A --jobs 8
python -m harmonize.pipeline --from-paired $PA $PB --out-dir outputs_full --jobs 12
python scripts/tiers.py outputs_full/validation/domain_scores.csv outputs_full/validation/tiers.csv
python scripts/drift.py outputs_full/drift $PA $PB --jobs 8
python scripts/drift.py outputs_full/drift $PA $PB --jobs 12 --sources MODIS_TERRA MODIS_AQUA --suffix _terra_aqua
C=outputs_full/calibration_coefficients.json
for h in A B; do python -m harmonize.pipeline --data-dir data_$h --out-dir runs/harmonized/$h --coefficients $C --skip-validation; done
python -m harmonize.pipeline --data-dir data_backcast --out-dir runs/backcast --coefficients $C --skip-validation
python scripts/backcast_check.py $C data_backcast runs/backcast runs/harmonized/A runs/harmonized/B outputs_full/backcast
python scripts/plot_full.py outputs_full
python -m pytest -q
```

Set `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1` when using `--jobs`, so the worker processes
do not oversubscribe the cores.

Committed outputs, in `outputs_full/`:
- `calibration_coefficients.json`;
- `validation/` with `scores`, `summary`, `folds` and `tiers`, plus `domain_scores_*.csv.gz`
  split by day/night;
- `crosstest/*/` with `scores`, `summary`, `tiers` and `domain_scores.csv.gz`;
- `drift/`, `backcast/` and `plots/`.

`monthly_oof.csv` (1.3 GB for the validation) is not committed; it is regenerated by the
commands above.

Single-pass commands, as before:

```bash
.venv/bin/python -m harmonize.pipeline --data-dir data_global --out-dir outputs_global   # end to end
.venv/bin/python -m harmonize.validate outputs_global/paired.parquet outputs_global      # validation only
.venv/bin/python -m harmonize.plots outputs_global/paired.parquet outputs_global         # figures only
```

From Python: `run_validation(paired_by_source, cfg, models=None, schemes=SCHEMES,
metrics=METRICS, sources=MODIS_CONFIGS, daynights=DAYNIGHT, n_jobs=None)` returns the five
tables and writes them as CSVs. `make_plots(paired_by_source, harmonized_or_None,
coef_or_None, cfg)` writes `plots/*.png`.

Figures:
- `outputs_full/plots/drift_ratio.png`: yearly VIIRS/MODIS ratio, indexed, per platform;
- `bias_vs_size_kfold.png`: |bias| against country-year size under domain K-fold;
- `backcast_series.png`: 2001-2024 VIIRS-equivalent series for the 31 back-cast countries;
- `map_ratio_and_k.png`, `scatter_modis_vs_viirs.png`: as before.

## Appendix A. Baseline: earlier 12-country test set (2019, 2023)

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

### A.1 Caveats on the baseline numbers

- The model choice is made on the same scores it is reported with. With 15 candidate
  combinations, the winner's 13.1 % / 9.8 % are slightly optimistic. The feature set was
  also tuned on these 12 countries.
- The p90 over 24 domain-years is about the 3rd-worst value. Countries are weighted equally
  whatever their size, so Greece (about 40 k VIIRS detections per year) weighs as much as
  Brazil (about 7 M).
