# Ianis's benchmark: our model vs his, VIIRS scale, MODIS-only predictions

Followed `harmonizare/BENCHMARK/BENCHMARK.md` on `origin/ianis_harmonization` (commit `d6301da`),
with his `score.py` and his truth table, unchanged. Scores are nmae = Σ|pred − obs| / Σ obs at
unit-month level, in %; lower is better; differences under 2 points are noise. nrmse and the
other columns are in `outputs_full/benchmark_ianis/scores_all.csv`.

## What was run

- **No leakage.** Our saved coefficients are trained on 2012-2024, so the models were refitted
  on **2012-2017 only** (`scripts/benchmark_ianis.py fit`).
- **MODIS only.** MODIS detections of 2018-2023 → the pipeline's `modis_as_viirs_equivalent`
  (`harmonized._calibrated`), per 0.25° cell, month, day/night. No VIIRS is used.
- **Models.** Ours: `glm_cell` (our pick for counts and FRP) and `glm_regional`, Terra + Aqua.
  His: `pred_n` / `pred_frp` from his truth file (Aqua only, fitted on 2012-2017).
- **Seen countries:** ours fitted on all 236 countries, scored on all countries.
- **Unseen countries:** ours fitted on half A only, scored on the half-B countries
  (`--countries`, 119 countries). His model has seen these countries, so this row is ours
  unseen against his seen.

## One problem in the scorer

`score.py` keeps only healthy months (`month_ok`) of the truth, but not of an external
prediction file: predictions for the 12 excluded months (Aug-Sep 2020 and 2021, eight months of
2022-2023) are scored against a truth of zero. Run as is, our global nmae came out at 17 % for
2018-2021 and 53 % for 2022-2023. The excluded months were removed from our prediction files
before scoring; the scorer was not changed. His own published scores reproduce exactly.

## Results, 2018-2021, plain truth (nmae %: global / region / country / 1° block / cell)

**Countries our model was trained on**

| | ours (`glm_cell`) | Ianis | winner |
|---|---|---|---|
| counts, day | 3.5 / 6.0 / 8.5 / 20.2 / 38.0 | 4.8 / 7.2 / 9.3 / 20.9 / 38.1 | tie |
| counts, night | 6.4 / 14.4 / 18.3 / 45.4 / 75.1 | 10.8 / 21.8 / 26.7 / 59.8 / 92.2 | **ours**, every level |
| counts, day + night | 3.1 / 5.6 / 8.2 / 21.2 / 39.4 | 5.1 / 7.8 / 10.4 / 24.3 / 42.7 | **ours**, every level (2.0-3.3 points) |
| FRP, day | 2.9 / 5.2 / 7.2 / 20.1 / 39.3 | 5.0 / 8.7 / 10.8 / 26.4 / 46.9 | **ours**, every level |
| FRP, night | 8.1 / 15.1 / 18.8 / 46.0 / 67.9 | 17.3 / 27.8 / 32.5 / 64.8 / 86.0 | **ours**, every level |
| FRP, day + night | 2.9 / 5.3 / 7.2 / 20.0 / 38.6 | 5.2 / 9.2 / 11.4 / 26.9 / 46.7 | **ours**, every level |

**Countries our model never saw** (his model has seen them)

| | ours (`glm_cell`, fitted on half A) | Ianis | winner |
|---|---|---|---|
| counts, day | 4.7 / 11.3 / 14.3 / 26.7 / 43.4 | 4.5 / 7.3 / 9.4 / 21.5 / 38.7 | **Ianis** from region down (4-5 points) |
| counts, night | 13.4 / 23.7 / 28.4 / 53.2 / 77.3 | 13.8 / 26.3 / 29.7 / 62.1 / 90.8 | **ours** at region, block, cell; tie at global and country |
| counts, day + night | 4.6 / 10.6 / 13.5 / 27.4 / 44.1 | 5.8 / 9.5 / 11.6 / 25.7 / 43.7 | tie |
| FRP, day | 3.2 / 8.2 / 10.3 / 23.7 / 41.7 | 5.5 / 9.7 / 11.4 / 27.7 / 47.7 | **ours** at global, block, cell; tie at region and country |
| FRP, night | 16.8 / 22.0 / 25.1 / 46.0 / 63.4 | 22.4 / 33.6 / 36.5 / 67.3 / 85.5 | **ours**, every level |
| FRP, day + night | 3.2 / 8.0 / 10.1 / 23.4 / 40.6 | 6.4 / 10.8 / 12.5 / 28.5 / 47.6 | **ours**, every level |

- **nrmse** gives the same winners, with two exceptions on seen countries: day counts at cell
  level are a tie (92 vs 91), and for unseen countries his night counts are ahead at global level
  (17 vs 19) while ours are ahead from region down.
- **Masked truth** changes no winner on seen countries, except that night counts become a tie
  at global level (8.8 vs 9.6). On unseen countries night counts become
  a tie at global, region and country (10.7 / 23.5 / 27.8 vs 12.2 / 24.0 / 27.6).
- **`glm_regional`** is within 1 point of `glm_cell` almost everywhere; `glm_cell` is 1-2 points
  better on seen countries at country and block level.
- **Country view, seen countries** (countries with enough fire): median |bias of the 2018-2021 total|
  6.0 % (ours) vs 11.9 % (his) for counts, 5.1 % vs 15.7 % for FRP; share of countries within
  ±20 %: 76 % vs 66 % (counts), 80 % vs 62 % (FRP); median monthly rank correlation 0.94 vs 0.92.

## 2022-2023 (secondary; Terra drifts)

- Seen countries: same picture. Ours ahead on FRP and on night counts at every level, day counts
  a tie, day + night counts ours by 1.5-2.5 points.
- Unseen countries: **his counts are better** for day + night (4.2 / 8.0 / 10.6 vs
  7.0 / 12.6 / 15.7 at global / region / country) and for day; FRP stays ours.

## Reading

- Where our model has seen the country, it is equal on day counts and better on everything
  else, most clearly at night and on FRP.
- Where it has not, his day counts are better; ours keep the lead on FRP and on night maps.
  This comparison favours him, since his factors were fitted on those countries.
- In production both models are fitted on every country, so the "seen" table is the relevant
  one for the app.

## Asymmetries

- Our months are UTC months, his are local-solar-date months.
- Ours uses Terra + Aqua, his Aqua only.
- His model was calibrated on the masked truth; ours uses no static-source mask.
- Countries per cell are his assignment (truth file).

## Rerun

```bash
W=runs/benchmark_ianis
python scripts/benchmark_ianis.py fit    $W runs/paired/A/all/paired.parquet runs/paired/B/all/paired.parquet
python scripts/benchmark_ianis.py export $W runs/harmonized/A runs/harmonized/B
# drop the months that are not month_ok from $W/pred_*.parquet, then for each model:
python ../ianis-wt/harmonizare/BENCHMARK/score.py --name glm_cell --pred $W/predok_glm_cell_all.parquet \
    --years 2018-2021 --truth plain --out $W/scores/seen_glm_cell_2018-2021_plain.csv
```
