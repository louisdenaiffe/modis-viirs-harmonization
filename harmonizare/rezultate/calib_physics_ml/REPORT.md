# calib_physics_ml — FRP-class weights (P1) and LightGBM (P3) vs ratios
Scope reduced by orchestrator: P2 and P4 dropped. Test = 2018-2021 via ec.evaluate. All fitting and model selection used 2012-02..2017-12 only.

## 1. Answer first
1. **Physics-style weights (P1) explain the night problem.** MODIS sees 1% of VIIRS night pixels below 3 MW, 11% at 3-6 MW and 16-19% at 6-50 MW (Aqua pixels per VIIRS pixel). 80% of VIIRS night pixels are below 3 MW (day: 10%). That is why the night count ratio is 0.034. By day the weights rise smoothly from 0.12 (<3 MW) to 0.35 (>=20 MW). For FRP, MODIS recovers 43% of VIIRS FRP below 6 MW and 92-111% above 20 MW (day). See `fig_detection_efficiency.png` and `p1_weights.csv`.
2. **P1 is the best night model on the board.** Night counts: median regional |bias| 4.3% (CR_B* 8.3-10.2%), cell MAE 0.35 (ratios 0.46-0.50), tercile 0.70. Night FRP: 7.9% (CR_B4 8.3%, others 10-12%). By day P1 only ties the ratios: counts 3.5% vs 2.1-3.0%, FRP 3.3% vs 2.9-3.5%.
3. **LightGBM (P3) is clearly best on counts for regions it was trained on.** Day: tercile 0.87 (best ratio 0.81), regional nMAE 5.3% (8%), median |bias| 2.3%. Night: |bias| 2.5%, tercile 0.77. For FRP it is no better than P1, and worse at night (11.6%). Its importance is dominated by VIIRS FRP: frp_sum 50%, frp_best 23%, f_6_10 15%. Raw counts carry only 1%.
4. **P3 does not generalise to new regions.** Leave-one-region-out day count bias: SHAF -23%, BOAS -30%, SEAS -25%. The P1 global weights fitted without that region: -8%, +31%, +4%. M1: -6%, +26%, +12% (`loro_comparison.csv`). Trust P3 only inside the training regions and period.
5. **Splice step on test years (default = P3 counts + P1 FRP).**
   - Counts: within ±6% in 12 of 14 regions. Worst are BONA (-12% day, -23% night) and CEAS (+15% night).
   - FRP night is still bad in EURO (-54%), EQAS (-32%), MIDE (-21%) and CEAS (+21%); every model has this.

| model (median reg. abs bias / worst / tercile) | n D | n N | frp D | frp N |
|---|---|---|---|---|
| M0 raw | 4.47/5.70/.25 | 28.3/65.1/.28 | .31/.77/.53 | 1.30/6.35/.37 |
| M1 global ratio | .134/.368/.67 | .196/1.26/.54 | .155/.411/.67 | .271/2.04/.56 |
| CR_B2 region x season | .026/.104/.81 | .083/.337/.65 | .031/.159/.78 | .101/.467/.65 |
| CR_B4 QM region-month | .025/.113/.79 | .096/.435/.68 | .031/.125/.82 | .083/.679/.72 |
| CR_B5 cell x season | .030/.124/.81 | .102/.338/.64 | .035/.104/.77 | .123/.335/.65 |
| P1 FRP-bin global | .149/.478/.70 | .214/.713/.63 | .057/.350/.74 | .156/.739/.66 |
| P1 FRP-bin region | .035/.123/.73 | .043/.341/.70 | .033/.143/.80 | .079/.540/.69 |
| P3 LightGBM | .023/.121/.87 | .025/.235/.77 | .041/.152/.85 | .116/.338/.75 |
| P3n+P1frp (apply_model) | .023/.121/.87 | .025/.235/.77 | .033/.143/.80 | .079/.540/.69 |

**Is it worth it?**
- By day, a region x season ratio (CR_B2/B4) gives nearly everything: about 3% regional bias.
- The real gains are at night (P1, P3) and in month-to-month fidelity (P3 tercile 0.87 vs 0.81).
- For a 2-day hackathon, ship CR_B4 or P1 for FRP and P1 for counts if explainability matters. P1 is 6 numbers per region with a physical story.
- Use the P3 counts model only as a "+ML" upgrade, labelled as not valid for unseen regions.

## 2. Built (`rezultate/calib_physics_ml/`)
- `apply_model.py`: `predict(df, counts='p3'|'p1') -> pred_n, pred_frp` from SNPP rows of the monthly table, any year 2012-2025. It was verified to reproduce the leaderboard rows and ran on 2024. CLI: `python rezultate/calib_physics_ml/apply_model.py 2024`
- `p1_weights.csv`: weights per region x D/N x FRP class.
- `p3_lgbm_counts.txt`: the LightGBM counts model.
- `p3_importance_{n,frp}.csv`, `loro_comparison.csv`, `fig_detection_efficiency.png`.
- Scripts in `work/calib_physics_ml/`. Order: s01_join, s02_p1 `<D|N> <n|frp> <ls|pois>`, s03, s04_eval, s05_fig, s06_p3 `<n|frp> [REGION]`, s07, s08. The intermediates were deleted for disk space, so rerun s01 first (under 60 s).

## 3. Method
- **P1:** Aqua monthly value = sum over 6 VIIRS pixel-FRP classes of a non-negative weight × the VIIRS count (or FRP) in that class. Weights come from a Poisson fit. I compared least squares vs Poisson and global vs region (0, 25% and 50% shrinkage to global) by leave-one-year-out within 2012-2017. Poisson with 25% shrinkage won.
- **P3:** LightGBM with Poisson loss (counts) or Tweedie 1.5 (FRP). 25 features. Trained on a 30% sample of 2012-2016, with 2017 for early stopping.

## 4. Caveats
- Count weights are below 1 partly because one MODIS pixel covers about 7 VIIRS pixels. They are an "equivalence factor", not a pure detection probability.
- The counts model never early-stopped (it hit the 800-round cap). No hyperparameter search was done.
- Cell MAE for counts differs by about 4% between the P3 and hybrid rows even though the region metrics are identical. I did not trace why.
- Not checked: whether the weights hold after 2021, or behaviour under the VIIRS type-flag bug.

## 5. Needs
None.

## Accuracy by area size (production recipe: DAY = calib_ratio B5, NIGHT = P1; test 2018-2021, Aug-Sep 2020 excluded)
Files: `accuracy_by_scale.csv` (for the app; bins are the PREDICTED value, because that is all the app knows), `accuracy_by_scale_obsbinned.csv` (same metrics, bins = real Aqua value), `accuracy_by_factor_group.csv`, `worst_1deg_blocks.csv`. Scripts: `work/calib_physics_ml/s10_build.py groups|2018..2021`, `s11_scale.py`, `s12_groups_worst.py`.

**1. Accuracy depends on how much fire is in the area, not on how big the area is.** Day counts, monthly, binned on the prediction. Each cell shows median |error|, the 10-90% range of pred/obs, and the share within ±20%.

| MODIS-eq pixels / month | 0.25° | 1° | 10° |
|---|---|---|---|
| 1-9 | 57% / 0.49-inf / 18% | 61% / 0.50-inf / 17% | 78% / 0.51-inf / 15% |
| 10-99 | 24% / 0.69-1.91 / 43% | 27% / 0.68-2.23 / 39% | 33% / 0.69-2.76 / 33% |
| 100-999 | 14% / 0.83-1.43 / 66% | 13% / 0.81-1.40 / 67% | 16% / 0.80-1.54 / 59% |
| ≥1000 | n/a | 9% / 0.90-1.21 / 87% | 9% / 0.89-1.27 / 81% |

- At the same fire activity, a larger area is slightly *worse*: few fires spread over a big box mean scattered, sporadic fires.
- Night is similar: 100-999 → 15-19%, ≥1000 → 10%.
- FRP needs roughly 10× more activity for the same accuracy: ≥10,000 MW/month → 14% (day) or 17-27% (night); 1,000-10,000 MW → 27-32%; below 1,000 MW → over 50%.
- Annual totals are better: day counts 100-999/yr → 11%, ≥1000/yr → 6-7% (about 92% within ±20%).
- Part of this error is not the model. Aqua and S-NPP pass at different minutes and see different clouds, so the error is an upper bound on model error.

**2. Coverage of the factors (day).** I grouped cells by how much S-NPP fire they had in the calibration years 2012-2017. "Own factor" means at least 1,000 pixels there (the B5 cell factor is then at least 50% the cell's own data). "2° block" means the cell has less but its 2° block reaches 1,000. "Region only" means even the block falls short.

| Group | Share of 2018-2025 VIIRS detections | Test bias | Cell-month error (≥100 px) | Region-year bias |
|---|---|---|---|---|
| Own cell factor | 71% | +3.1% | 13% | 4% |
| 2° block | 27% | +2.1% | 18% | 3% |
| Region only | 1.4% | +18% | 20% | 21% |

- So the model is **somewhat worse where 2012-2017 had little fire**, but that is only 1.4% of the activity.
- Night uses P1, which has no cell factors, so these groups matter less there: region-year bias 8% / 9% / 29%, and 4.4% of night activity is "region only".

**3. Worst 1° blocks** (day, at least 1,000 Aqua pixels in 2018-2021). 94% of the 1,905 such blocks are within ±20%, and 99.8% within ±50%. The outliers are almost all *episodic extreme fire years* that differ from the calibration fire regime:
- Yakutia 63-66°N 119-127°E: pred/obs 0.60-0.72 (2019-21 megafires, only 8-17 active months, 2-2.5 overpasses/day).
- Alaska 66.5°N -143.5°: 1.69 day, 0.47 night (4 active months).
- Paraná delta / Entre Ríos -32.5°S -60.5°: 1.77, and -30.5°S -59.5°: 1.54 (2020-21 wetland and pasture burning).
- N Thailand 18.5°N 100.5°E: 1.48 (cropland, small fires: 19% of pixels below 3 MW).
- SW Australia -33.5°S 123.5°E: 0.62; -32.5°S 116.5°E: 1.43.
- Sierra Nevada 36.5°N -118.5°: 1.43 (2020-21 megafires).
- At night, Iceland 63.5°N -22.5°: 0.49 count, 0.15 FRP. This is the 2021 Fagradalsfjall eruption, a volcano labelled as vegetation (v2 type bug).
- At night, E Gippsland -37.5°S 148.5°E: 2.10 (Black Summer 2019-20).
- No gas-flare blocks appear in the list: the persistent cell factors absorb them.

**4. Rule of thumb for the app.**
- An area with about **1,000 or more MODIS-equivalent detections in the month** (or summed FRP of 10,000 MW or more) is accurate to about **±10%** (counts) or **±15-25%** (FRP).
- **100-999 detections**: about ±15%; label "moderate confidence".
- **10-99 detections**: about ±25-35%; label "low confidence" and show the range from the CSV.
- **Below 10 per month**: do not quote a number. Show "few fires" only, or switch to the annual total, which is about twice as accurate.
- A single episodic megafire season in a box can still be off by ±40%.
