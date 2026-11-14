# Harmonizing MODIS and VIIRS active-fire hotspots — method

Prototype, NASA Space Apps. All numbers come from the 2025 / Italy run
(`python -m harmonize.pipeline`) and were re-checked by hand.

**Bottom line.** Use **fire cell-days** (days with at least one detection per 0.25° cell and
month) as the activity metric, and convert MODIS (Terra + Aqua) with a **single ratio**:
`VIIRS-equivalent = 3.21 × MODIS fire cell-days`, with day and night pooled. Out of sample, the
national monthly totals are within ±6 % (worst of four hold-out schemes, pooled) and monthly
R² is ≥ 0.98. This is a **one-year, one-country prototype**. The factor must be refitted on
2012-2024 before any back-cast is trusted.

## 1. Goal

Produce one fire-activity time series in **VIIRS-equivalent units**: VIIRS S-NPP (375 m,
2012+) where it exists, and MODIS (1 km, 2000+) converted to "what VIIRS would have seen"
elsewhere, so the 2000-2011 MODIS-only years can be put on the same scale as the VIIRS era.

## 2. Data and common schema

NASA FIRMS archive CSVs (every `*.csv` in `data/`). MODIS C6.1 (Terra + Aqua) and VIIRS
S-NPP 375 m. The sensor is detected from the columns (`brightness`/`bright_t31` vs
`bright_ti4`/`bright_ti5`), and both are mapped to one point table (`SCHEMA.md` §1): common
names for brightness temperatures, FRP, pixel size, a 3-class confidence, the FIRMS `type`,
and a UTC timestamp. The full contract is in `SCHEMA.md`, and every setting is in
`harmonize/config.py`. Nothing hard-codes a country, a year or a file name.

## 3. Filtering

* `type == 0` (presumed vegetation fire). Volcanoes, static land sources and offshore detections are dropped.
* Confidence `>= nominal`. MODIS 0-100 is binned as low <= 29, nominal 30-79, high >= 80,
  which matches VIIRS l/n/h. The low-confidence class is dropped for both sensors.
* Exact duplicates across overlapping files are removed.

## 4. Aggregation and metrics

Points go into a 0.25° grid by calendar month (UTC), separately for day, night and both
(D/N/ALL computed from the points). MODIS_ALL is Terra ∪ Aqua. Three candidate metrics:

| metric | meaning | why |
|---|---|---|
| `n_hotspots` | number of detections | most direct, but depends strongly on pixel size (375 m vs 1 km) |
| `fire_cell_days` | distinct days with ≥ 1 detection in the cell | less sensitive to pixel size and to how many pixels one fire covers |
| `frp_sum` | summed fire radiative power (MW) | physical, but MODIS and VIIRS FRP differ in saturation and per-pixel sensitivity |

The paired table is the **union** of cell-months seen by either sensor, zero-filled, and
restricted to months both sensors cover. In 2025, 58 % of cell-months have MODIS = 0 and
VIIRS > 0, and they hold 24 % of all VIIRS detections.

## 5. Calibration models compared (`harmonize/calibrate.py`)

All models are fitted at cell-month level, y = VIIRS and x = MODIS:

* `ratio`: y = k·x, with k = Σy/Σx. All VIIRS mass, including VIIRS-only cells, is folded into cells that MODIS saw.
* `loglog`: log(y+1) = a + b·log(x+1), back-transformed with Duan smearing.
* `poisson`: E[y] = e^a (x+1)^b, fitted by Poisson pseudo-likelihood.
* `powerlaw_total`: E[y] = c·x^b for x > 0 and 0 at x = 0, with c rescaled to the total.

Pooled 2025 factors (MODIS_ALL, day+night): k = 4.49 for hotspots, 3.21 for fire
cell-days and 1.27 for FRP.
<!-- RESULTS:coefficients -->

## 6. Validation design (`harmonize/validate.py`, independent of the fitting code)

Only `fit_model`/`apply_model` are reused. Folds and scores are computed separately, and
the in-sample fit statistics are never read. Each scheme tests every row exactly once, so
scores are computed on the pooled out-of-fold predictions. Per-fold spread is also stored
in `fold_scores.csv`.

| scheme | train / test | what it tests |
|---|---|---|
| `temporal_lomo` | leave one month out (12 folds) | month-to-month transfer within one year |
| `temporal_blocked` | Jan-Jun ↔ Jul-Dec, both directions | transfer between **fire regimes**: the Jun-Sep fire season is almost all in H2, so this is "calibrate on a quiet half, apply to the peak" and the reverse. It is the closest proxy we have for applying 2025 factors to another year with different fire activity. |
| `spatial_kfold` | 5 folds of cells, grouped by `cell_id`, fixed seed | transfer to unseen cells inside the same region mix |
| `spatial_ns` | north vs south of the median cell latitude (41.875° N), both directions | transfer between **regions** (Alpine/Po valley vs Mediterranean south) |

**Evaluation mode.** In a back-cast year, cells with MODIS = 0 do not exist, so we
score in **back-cast mode**: the prediction is forced to 0 where MODIS = 0, and it is
compared with *all* VIIRS. A `union` mode, which also applies the model at x = 0, is
reported as well.

**Scores** (test data, predicted vs observed VIIRS):

* bias % of total
* R² on log1p at cell-month level, over all rows and over rows with MODIS > 0 (`r2_log_pos`)
* raw-scale R²
* R² of national monthly totals
* Spearman correlation of the monthly totals (over the test cells for spatial folds)
* MAE

R² is 1 − SS_res/SS_tot, so it can be negative. The baseline `raw_modis` (no calibration)
is scored the same way.

**Ranking** (`summary.csv`). For each model, take its worst value over the four schemes
for |bias|, `r2_log_pos`, monthly R² and Spearman, then average the ranks. Ranking on the
worst case favours a calibration that keeps working when the season or region changes.

## 7. Results (2025, Italy, MODIS_ALL, day+night, back-cast mode)

<!-- RESULTS:validation_table -->
| metric | model | worst \|bias\| over schemes | mean \|bias\| | min R² monthly | min Spearman (months) | min R² log (MODIS>0) |
|---|---|---|---|---|---|---|
| fire_cell_days | **ratio** | **5.6 %** | 2.2 % | **0.98** | 0.99 | −0.05 |
| fire_cell_days | powerlaw_total | 24.3 % | 7.3 % | 0.80 | 0.99 | −0.18 |
| n_hotspots | ratio | 19.4 % | 5.4 % | 0.90 | 0.98 | 0.19 |
| n_hotspots | powerlaw_total | 39.9 % | 11.6 % | 0.56 | 0.98 | 0.05 |
| frp_sum | ratio | 32.1 % | 9.6 % | 0.78 | 0.87 | 0.25 |
| any | loglog / poisson | 59-73 % | 33-52 % | < 0.45 | 0.82-0.96 | < 0 |
| fire_cell_days | raw MODIS (no calibration) | 68.9 % | 68.9 % | −0.01 | 0.99 | 0.29 |
| n_hotspots | raw MODIS (no calibration) | 77.7 % | 77.7 % | −0.10 | 0.99 | 0.28 |
| frp_sum | raw MODIS (no calibration) | 21.4 % | 21.4 % | 0.90 | 0.87 | 0.33 |

Per-scheme bias for the best model (fire_cell_days / ratio) is LOMO +0.6 %, blocked +1.9 %
(fold-level −4.3 % / +4.5 %), spatial k-fold +0.7 % (folds −14 % to +17 %) and N/S −5.6 %
(north +11 %, south −10 %). For n_hotspots / ratio the N/S folds are +40 % / −28 %, which
means the VIIRS/MODIS hotspot ratio differs between regions much more than the cell-day
ratio does.
<!-- RESULTS:end -->

**Aqua-only vs Terra + Aqua** (ratio, day + night, back-cast mode, worst case over schemes):

| metric | MODIS source | k | worst \|bias\| | min R² monthly |
|---|---|---|---|---|
| fire_cell_days | Terra + Aqua | 3.21 | 5.6 % | 0.98 |
| fire_cell_days | Aqua only | 5.14 | 12.4 % | 0.89 |
| n_hotspots | Terra + Aqua | 4.49 | 19.4 % | 0.90 |
| n_hotspots | Aqua only | 7.12 | **5.4 %** | **0.97** |

Aqua and S-NPP cross at nearly the same local time, so they see the same point in the
daily fire cycle. That explains why the hotspot-count ratio becomes stable once Terra is
removed. For hotspot counts, using Aqua alone is close to the best choice. For cell-days,
combining Terra and Aqua helps, because each extra overpass adds new days.

**How the two analyses were reconciled.** The calibration module ranks candidates by its own
leave-one-month-out (LOMO) error on national totals. On LOMO, n_hotspots/ratio and
fire_cell_days/ratio are tied (WAPE 9.7 % for both, bias −0.5 % and +0.6 %). The
independent validation adds spatial hold-outs, and these separate the two metrics:
north→south / south→north bias is −19 % / +24 % for hotspots and −9 % / +10 % for cell-days
(recomputed by hand). The pipeline therefore takes the final `recommended` block in
`calibration_coefficients.json` from the independent validation summary. It keeps the
calibration module's pick under `calibration_module_pick` for reference. One caveat: because
the validation is used to choose the model, it is no longer a fully untouched test of the
model it chose.

What we take from this:

1. **Use `fire_cell_days` with a single `ratio`.** It is the most transferable choice:
   bias stays within ±6 % pooled in every scheme and within ±17 % in any single fold.
   Monthly totals reach R² ≥ 0.98.
2. **Log-space models fail for totals.** loglog and poisson under-predict back-cast totals
   by 30-70 %. Their fit is driven by the many small cells, the big cells that dominate the
   totals get too little, and part of their mass sits at x = 0.
3. **Use the output for national/regional monthly series, not single cells.** Calibrated
   predictions do not beat raw MODIS at cell level (`r2_log_pos` ≤ 0.25 vs 0.29). The
   ratio moves the VIIRS-only mass into cells MODIS saw.
4. **Calibrate day + night together.** Night ratios are 5-60× and strongly seasonal. A
   night-only ratio has pooled biases up to 92 %, and the LOMO folds range from −100 % in
   winter to +60 % in July.
5. **The month ranking is the same with or without calibration.** Spearman is about 0.99
   even for raw MODIS. Calibration fixes the *level* (−69 % → ±6 %), not the seasonality.
6. **FRP needs little scaling but transfers poorly.** Its pooled ratio is only 1.27, but it
   moves between regions (N/S −32 %).

Figures in `outputs/plots/`:

* `scatter_modis_vs_viirs.png`
* `monthly_before_after.png`
* `monthly_ratio.png` (by day/night and by Aqua vs Terra)
* `validation_oof_monthly.png` (out-of-fold monthly totals)

## 8. Limitations

* **One year, one country.** This is a prototype. Every hold-out stays within 2025 and
  within Italy, so none of them tests transfer between years, which is what the back-cast
  needs.
* **Detection physics.** The 375 m VIIRS I-band detects smaller and cooler fires than the
  1 km MODIS C6.1 algorithm, so the ratio depends on the fire-size distribution (landcover,
  season, region). This explains the N/S differences, and a constant k is only a
  first-order approximation.
* **Orbits.** Terra has drifted to an earlier crossing since about 2020 (now around 10:00 or
  earlier instead of 10:30) and Aqua since about 2022. 2025 MODIS therefore samples
  different times of the diurnal fire cycle than 2003-2019 MODIS did. Terra alone already
  needs 2-3× the Aqua ratio. Factors fitted on 2025 may be biased for the stable-orbit years.
* **Reference satellite.** S-NPP is the reference. NOAA-20/21 have different overpass
  phasing and slightly different counts and are not used, so the S-NPP ↔ NOAA-20 offset
  would need its own check.
* **FRP.** MODIS detects only higher-FRP pixels and VIIRS I4 saturates on intense fires,
  and the two sensors resolve pixels differently. FRP sums are not directly comparable.
* **Small cells and zero inflation.** 0.25° × month cells are sparse: 58 % of the union
  rows have MODIS = 0, and many have only 1-2 detections. Cell-level skill is low, and
  results are only meaningful once aggregated.
* **Cell-day cap.** A plain ratio can push a cell above the number of days in the month,
  which happened in 16 of 2,302 cell-months in 2025. `harmonized.csv` clips
  `modis_as_viirs_equivalent` to that limit, so the in-sample national total is −1 %
  (6,437 vs 6,503 VIIRS cell-days).
* **Spatial resolution of the output.** At cell level the converted MODIS value is a
  scaled-up version of what MODIS saw. It cannot recreate the small fires MODIS missed in
  other cells. The calendar should show national or regional totals, with cells as
  supporting detail.

## 9. With 2012-2024 data, and the 2000-2011 back-cast

* Refit on 2012-2024 (S-NPP + Terra/Aqua overlap) and add a **leave-one-year-out** scheme.
  It becomes the primary test, with LOMO, N/S and k-fold kept as secondary checks. Report
  the ratio's year-to-year coefficient of variation, and whether it trends with the
  Terra/Aqua orbit drift. If it does, fit only on 2012-2019, before the drift.
* Consider a seasonal term (month or fire-season dummy) and a regional term, and keep them
  only if they beat the constant ratio out of fold.
* For 2000-2011, apply the fitted factors (`--coefficients outputs/calibration_coefficients.json`)
  to MODIS. Aqua data only starts in mid-2002. Before that, the Terra-only factor
  (`MODIS_TERRA`, k = 7.39 for cell-days in 2025) must be used: applying the Terra + Aqua
  factor to Terra alone would under-estimate activity by about 2×. The pipeline does
  **not** switch factors by date yet; this is the first thing to add.
* With many years, the Aqua-only hotspot model (the runner-up above) can be tested properly.
  If it is more stable across years, it is the natural choice for 2002-2011. Every back-cast value carries `source_flag = MODIS_CALIBRATED`, with an
  uncertainty band taken from the spread of out-of-fold biases.

## 10. Outputs (`outputs/`)

* `harmonized.csv`: one row per cell × month × D/N/ALL, for the recommended metric. Columns:
  `modis_raw`, `viirs_raw`, `modis_as_viirs_equivalent`, `harmonized_value`, `source_flag`
  (`VIIRS` where VIIRS covers the month, otherwise `MODIS_CALIBRATED`).
* `calibration_coefficients.json`: every metric × model × source × D/N fit plus the
  recommendation. It can be reapplied to another year with `--coefficients`.
* `hotspots_clean.csv`: filtered point-level hotspots in the common schema (for download).
* `aggregated.csv`, `paired.csv`, `calibration_stability.csv`, `validation/*.csv`, `plots/*.png`.

## 11. How to rerun

```bash
.venv/bin/python -m harmonize.pipeline --data-dir data --out-dir outputs   # end to end
.venv/bin/python -m harmonize.pipeline --data-dir data_modis_only --out-dir backcast \
    --coefficients outputs/calibration_coefficients.json                   # apply only (back-cast)
.venv/bin/python -m harmonize.validate outputs/paired.csv outputs          # validation only
.venv/bin/python -m harmonize.plots outputs/paired.csv outputs             # figures only
.venv/bin/python -m pytest -q                                              # tests
```

Validation CSVs are written to `outputs/validation/`:

* `scores.csv`: pooled out-of-fold scores
* `fold_scores.csv`
* `monthly_oof.csv`
* `summary.csv`: ranking
