# calib_ratio — simple, explainable VIIRS -> Aqua-equivalent transfer

## 1. Answer first
1. **Harmonize counts (n_sum) and FRP (frp_sum), not presence metrics.** Your expectation that FRP and presence metrics are more stable is refuted. Year-to-year CV of the regional Aqua/SNPP ratio (median over regions), day / night: counts 0.031 / 0.124, FRP 0.069 / 0.156, active days 0.058 / 0.183, active cells 0.041 / 0.168. Region-month NMAE after a regional ratio, day: counts 0.104, FRP 0.102, days 0.160, active cells 0.194. FRP only *looks* stable because its raw ratio is near 1 (day 0.80). n_best adds nothing except at 60-70N.
2. **Recommended model: B5 = region x season factor x shrunk cell factor.** Against M1 (one global ratio), median regional |bias| on counts falls from 13.4% to 3.0% (day) and 19.6% to 10.2% (night). Worst region on night FRP falls from 204% to 33%. Region-month NMAE on day counts falls from 0.158 to 0.078, and tercile agreement on day counts rises from 0.67 to 0.81.
3. **Splice test: day has no visible step, night still has one.** Real Aqua 2003-17 followed by predicted 2018-21, compared with real Aqua 2018-21. Median |step| over 14 regions: counts D 3.0% / N 10.3%, FRP D 3.5% / N 12.5%. Worst cases are all at night: BONA counts -27% (90% CI -31 to -22), MIDE counts +33%, EQAS FRP -33%. Top-10%-month flags agree with precision/recall of 0.89/0.93 (counts D) and 0.85/0.89 (counts N).
4. **The 80% region-month interval is about right.** Test coverage: counts 0.77 (D) / 0.76 (N), FRP 0.79 / 0.82. Typical width for busy day region-months is x0.86 to x1.11.
5. Lat-band x continent strata gave <0.1% LOYO gain, so they were dropped. Quantile mapping (B4) gives the best tercile agreement on FRP (D 0.82, N 0.72), but its worst-region bias reaches 68% at night.

## 2. Built (in harmonizare/)
- `rezultate/calib_ratio/factors.parquet` (and .csv): the factor table. Levels are region_season, b2 (relative), cell (relative), interval_cell and interval_regionmonth.
- `rezultate/calib_ratio/apply_model.py`: `predict(df)` takes ix, iy, year, month, daynight, n_sum, frp_sum and returns pred_n, pred_frp and lo/hi bounds per cell. `regional_interval()` gives bounds for summed predictions. To regenerate the region-month series, run `python3 apply_model.py 2012 2025`; it writes `harmonized_regionmonth.csv`.
- `fig_before_after.png`: SHSA, SHAF, BOAS, SEAS, day counts (log scale) and FRP, 2003-2021, with the interval band. Plotted values for SHAF in Aug 2019: Aqua 233,284 pixels, raw VIIRS 1,072,871, harmonized 257,854; FRP 9.52, 12.48 and 10.44 TW.
- CSVs: partA_*.csv (Part A), cv_B2.csv / cv_B3.csv / cv_B3h.csv (n0 search), splice_test.csv.
- Scripts are in `work/calib_ratio/`. Run order: prep.py, run_model.py `<B1|B2|B3|B5>`, qm.py, fit_prod.py, partC.py, partC2.py, splice.py, fig.py.

## 3. Method
- **The recipe.** k = K(region, day/night, season) x rel(cell). Predicted Aqua = k x VIIRS.
- **K (seasonal regional factor).** Aqua sum / VIIRS sum for one region, day/night and season, shrunk toward the full-year regional ratio: (A + n0·K_region)/(S + n0), with n0 = 3000 pixels for counts and 1000 MW for FRP.
- **rel (spatial adjustment).** The cell's own ratio, shrunk toward its 2° block and then toward the region (n0 = 1000 pixels, 10^4 MW), divided by the regional ratio. It is 1 where the cell and block have no data.
- **Choosing n0.** Leave-one-year-out within 2012-2017 only, picking from 3 candidate values.
- **Intervals.** 10th-90th percentiles of observed/predicted from the same year-out runs, binned by predicted magnitude.

## 4. Caveats
- Night remains weak: only 14% of VIIRS-active cell-months have any Aqua night detection.
- Steps of 10-30% remain in BONA, EQAS, MIDE and CEAS at night.
- The FRP n0 (10^4 MW) sits at the edge of the candidate grid.
- Cell-level intervals have a lower bound of 0 at low activity, so their coverage (0.88-0.95) is conservative.
- 2012 includes a partial January (VIIRS starts 20 Jan); 2022 has the S-NPP outage. Those totals are low because of data gaps, not fire.
- Applying the factors after 2021 assumes S-NPP itself is stable. That is plausible, because its overpass time is steady, but it cannot be verified against Aqua, which drifts from 2022.

## 5. Requests
- Use B5 for production.
- Consider an activity-dependent night term (B4 shows non-linearity: median obs/pred is 0.81 for night region-months under 100 pixels).
- To re-run the scripts, regenerate `pair_*.parquet` with prep.py (12 s); I deleted those files to save disk.

## Follow-up QA (14 Nov, afternoon)
**Verdict: ship v2 for daytime counts in BONA/BOAS only; leave everything else as v1; no global de-bias.**
1. **Junction audit** of `rezultate/final/region_month.csv`, file `junction_audit.csv`. Statistic: log(sum of the 12 months after the boundary / sum of the 12 months before), i.e. same calendar months on both sides. Placebo: the same statistic at the same boundary month in every year inside the real-Aqua era (n=18 per region).
   - **2002-07 (Terra back-fill to Aqua): one clear step, SHAF.** Counts D -22% (placebo range -11..+13%, z=-4.2); FRP D -26% (placebo -15..+14%, z=-3.8); FRP N -30% (outside). The back-fill is about 20% too high in SHAF, in the Jul-Oct 2001 season.
   - Other 2002-07 cases outside the placebo range are borderline, with |z| < 2.1 inside a highly variable placebo: CEAS D +42%, NHSA D/N, SEAS D FRP.
   - **2022-01 (Aqua to converted VIIRS): no step in daytime FRP; day counts only NHSA** (+38%, placebo max +36%, z=1.5, consistent with a real 2022 fire year).
   - At night, MIDE FRP -80% (z=-3.1), NHAF FRP -31% (z=-2.0) and NHSA N +216% / +334% are outside the placebo range. These are small totals inside the night P1 conversion, which I did not re-fit.
   - Global series: no junction is outside the placebo range.
   - Action for the orchestrator: check the Terra-to-Aqua factor for SHAF (owned by qc_stability).
2. **High latitudes (day).**
   - Test 2018-21 results, BONA bias / region-month NMAE for counts:
     - v1: +9.7% / 0.236
     - (a) split at 60N: +5.9% / 0.176
     - (b) n_best as the VIIRS input: +1.9% / 0.152
     - (a)+(b): **0.0% / 0.119**
     - (c) activity bins (4 levels of VIIRS pixels per cell-month, fitted on calibration years only, total preserved): +8.7% / 0.255, rejected for day.
   - BOAS, v1 -> (a)+(b): bias +1.7% -> -2.1%, NMAE 0.066 -> 0.050.
   - **Same ranking on calibration years only** (leave one year out, 2012-17), region-month NMAE: BONA 0.200 -> 0.145, BOAS 0.092 -> 0.082.
   - Yakutia box (58-72N, 105-150E), Jul-Aug 2021: Aqua 77,716 pixels; v1 72,478 (-6.7%); v2 75,337 (-3.1%).
   - FRP: the latitude split did not help consistently (BOAS bias -5.4% -> -6.3%). FRP stays v1.
   - Night: activity bins would cut the B5 BONA night bias from -27% to -24%. But production night is P1_frpbin_region, which already has BONA +3.9% and BOAS +7.1% on counts, so there is nothing to fix.
   - Other regions are unchanged by construction. Leaderboard row CR_V2_B5_nbest_lat60_BO: day counts glob_bias +2.78% (v1 +3.01%), cell_mae 1.866 (v1 1.868), tercile agreement 0.818 (v1 0.806). Night and FRP are identical to v1.
3. **Systematic +3% on day counts: not de-biased.**
   - The annual Aqua/S-NPP count ratio is 0.2093, 0.2038, 0.1998, 0.2040, 0.2029, 0.2052 for 2012-17 and 0.1999, 0.2004, 0.2001, 0.1980 for 2018-21.
   - Trend within the calibration years: -0.27%/yr (p=0.52, not significant). Extrapolated, it explains only -1.3% of the 2018-21 drop of -2.2%.
   - The test years sit about 1.5 calibration standard deviations (sd of log ratio 1.5%) below the calibration mean, and 11 of 14 regions are lower.
   - Reading: it is consistent with a slow drift (Aqua or S-NPP degradation) but not detectable from calibration years alone. A de-bias is not justified; report it as about ±3% systematic uncertainty. FRP day shows no shift (-0.05%).
4. **Counts and FRP are calibrated separately** in production, each with its own factors and shrinkage constants (and, for night P1, its own FRP-class weights). Fitting them jointly cannot change the sums: their ratios differ by about 4x (day 0.20 vs 0.80), and each ratio of sums is already the best estimate for its own variable. Joint fitting would matter only if counts and FRP had to stay consistent with each other (e.g. FRP per pixel), which nothing downstream needs.

Files: `factors_v2.parquet` (v1 rows plus var=`n_best_hilat` for BONA_lo/hi and BOAS_lo/hi), `apply_model_v2.py` (same `predict(df)`; needs an `n_best` column, otherwise falls back to v1), `junction_audit.csv`. Scripts are in `work/calib_ratio/` (junction.py, drift.py, hilat.py `<base|lat|nbest|nbest_lat|act>`, hilat_loyo.py, fit_v2.py, yak.py).
To use v2 in production: in `04_build_final.py`, call `apply_model_v2.predict` for day, passing `n_best` from `monthly_025`.
