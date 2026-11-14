# Benchmark: comparing two MODIS/VIIRS harmonization models fairly

Branch `ianis_harmonization`, folder `harmonizare/`. This page tells you (or your AI assistant) exactly how to score
another model against ours with the same data, the same truth and the same code.

## What our model is (one paragraph)
Calibrated ratio factors, not ML. Monthly values on a 0.25° grid, day (D) and night (N) separately, counts and FRP calibrated
separately. Filters: FIRMS `type == 0`, confidence not low, plus a static-source mask (flares, industry, lava).
Calibration period 2012-02..2017-12, all countries. It produces the record on two scales:
- MODIS scale (VIIRS -> Aqua-equivalent): `rezultate/calib_ratio/apply_model_v2.py` (day), `rezultate/calib_physics_ml/apply_model.py` with `counts='p1'` (night).
- VIIRS scale (Aqua -> VIIRS-equivalent): `rezultate/calib_ratio/apply_model_reverse.py`. **This is the one comparable to a model that outputs VIIRS-equivalent units.**
Our MODIS input is Aqua only (same overpass time as S-NPP). Full description and numbers: `harmonizare/CITESTE-MA.md` (Romanian).

## The test (back-cast on held-out overlap years)
Question: *given only MODIS, how well does each model predict what VIIRS really measured?*
- Truth: real S-NPP VIIRS monthly detections and FRP per 0.25° cell, 2018-2023, in `truth_and_ours_2018_2023.parquet`
  (columns `viirs_n`, `viirs_frp` = type 0 and confidence not low; `viirs_n_masked`, `viirs_frp_masked` = same minus our static mask).
- Our predictions are already in that file: `pred_n`, `pred_frp` (made from Aqua only, with factors fitted on 2012-2017).
- Headline years: **2018-2021** (before the MODIS orbit drift). 2022-2023 is a secondary check: Terra drifts strongly from 2022
  (-10% to -42% detections by 2025), which hurts any model that uses Terra, so report it separately.
- `month_ok` marks months where Terra, Aqua and S-NPP were all fully healthy; the scorer uses only those.

## Rules that keep the comparison fair
1. **No leakage.** The other model must be fitted WITHOUT the test years (ours never saw 2018+). If its saved coefficients were
   trained on 2018-2021 data, refit on 2012-2017 only, or restrict the test to years it did not see, and say which.
2. **Predictions must come from MODIS only.** For the other model use its MODIS-converted column
   (`modis_as_viirs_equivalent`), never a blended column such as `harmonized_value` (which contains real VIIRS wherever VIIRS exists).
   For ours use `pred_n` / `pred_frp` from the truth file, never `n_veq` from `APP_DATA` (that is real VIIRS from 2012 on).
3. **Same truth, same scorer.** Convert the other model's output to: `ix, iy, year, month, daynight ('D'/'N'), pred_n, pred_frp`
   with `ix = floor((lon + 180) / 0.25)`, `iy = floor((lat + 90) / 0.25)` (cell lower-left corner on a 0.25° global grid), then run:
   ```
   python3 harmonizare/BENCHMARK/score.py --name ours
   python3 harmonizare/BENCHMARK/score.py --name other --pred other_pred.parquet
   ```
   Options: `--years 2022-2023`, `--truth masked`, `--countries Brazil,Greece,...`.
4. **Same domain.** If the other model was run on a subset of countries, score BOTH models with the same `--countries` list.
   Report separately the countries the other model was trained on and countries it never saw.
5. **Known small asymmetries (state them, do not hide them):** our months use the local solar date, a UTC-month model differs
   slightly at month boundaries; our model was calibrated on the masked truth, so `--truth plain` slightly favours an unmasked model
   and `--truth masked` slightly favours ours — report both; our input is Aqua only, the other model may use Terra+Aqua.

## What to report
`score.py` prints and saves, for D, N and ALL (day+night), counts and FRP, at five levels (global, region, country, 1° block, 0.25° cell):
- `bias` (signed; + and - cancel — context only),
- `nmae` = sum|pred - obs| / sum(obs) and `nrmse` = RMSE / mean(obs) at unit-month level (**these decide; errors cannot cancel**),
- per region/country: median |bias|, share of units within ±20%, worst unit, median monthly error, median Spearman rank correlation
  (does the model order the months correctly — what the fire calendar needs).
Decide per row, not overall: one model may win by day and lose by night, or win on countries and lose on cells.
Differences below ~2 percentage points are noise. If each model wins somewhere, the best product is a hybrid.

Our scores (2018-2021, plain truth): day counts nmae 4.8% global, 7.2% region-month, 9.3% country-month, 21% 1° block, 38% cell;
night counts 11% / 22% / 27% / 60% / 92%; day FRP 5.0% / 8.7% / 10.9%. Full table: `scores_ours.csv`.

## Optional second test: the 2011 -> 2012 junction
No truth exists before 2012, so this cannot rank models by itself. For each region compare the change in level across the junction
(12 months after vs 12 months before, same calendar months) with the same statistic at every other year boundary (placebo).
A model whose junction change falls outside the placebo range has a splice problem. Ours: `APP_DATA/region_month.csv` (`n_viirs`).

## Which files matter
| Use | Path |
|---|---|
| Benchmark data + scorer | `harmonizare/BENCHMARK/` |
| Final product for the app (both scales) | `harmonizare/APP_DATA/` (see `CITESTE-MA-APLICATIE.md`) |
| Our model code + factors | `harmonizare/rezultate/calib_ratio/apply_model_reverse.py`, `apply_model_v2.py`, `factors_*.parquet`; `harmonizare/rezultate/calib_physics_ml/apply_model.py`, `p1_weights.csv` |
| Pipeline scripts, in run order | `harmonizare/scripts/01_…08_*.py`, `eval_common.py` |
| Method reports | `harmonizare/rezultate/*/REPORT.md` |
| Not needed for the comparison | `output/` (early Albania pilot), the `.rtf` chat exports, `harmonizare/work/` (scratch scripts), `harmonizare/data/` (intermediate tables, not in git), files named `*_nomask.*` (pre-mask backups) |
Raw FIRMS CSVs (`MODIS_data/`, `VIIRS_data/`) are not in git; download them from https://firms.modaps.eosdis.nasa.gov/country/.
