# qc_stability — outages, orbit-drift impact, MODIS versions, Terra->Aqua back-fill

## 1. Answer first (all measured)
- **Aqua's daytime record against S-NPP holds up globally, but not in every region.** Change in the yearly Aqua/S-NPP index
  vs its 2012-2019 mean (year-to-year spread 2012-21 in brackets):
  - Day counts, global: 2022 -0.4%, 2023 +0.2%, 2024 +1.3%, 2025 -0.2% (spread 1.2).
  - Day FRP, global: -2.1%, +3.4%, +0.1%, **-7.2%** (spread 1.9).
  - Regions most affected in 2025: CEAM counts +16.6% / FRP +25.6%; SEAS FRP -21%; NHAF FRP -13%; SHAF FRP -12.4%;
    TENA counts -10.5%; EQAS FRP -39% (EQAS is a small, noisy region).
  - **Night 2025 counts: -18.6% global** (spread 5.0); SHAF -34.5%, SHSA -19.1%.
  - Conclusion: trust Aqua as the target through 2023. Treat **day FRP and night counts in 2024-25** as drift-affected
    (2025 clearly so).
- **Terra is no longer a reliable reference.**
  - Terra/S-NPP day counts: 2022 -9.4%, 2023 -16.4%, 2024 -28.8%, **2025 -41.8%** (SHAF -60%, NHSA -43%, NHAF -43%).
  - Terra/S-NPP day FRP 2025: -44.8% (SHAF -69%).
  - Terra/S-NPP night counts: **+28.6%** in 2025.
  - Terra/Aqua day counts: -11.3%, -16.9%, -34.1%, -41.8%. Terra/Aqua night counts 2025: +61%.
  - Do not use Terra after 2021 without a drift correction.
- **The MODIS version change in 2018 shows no step that matters.** The yearly Aqua/S-NPP day index averages +0.5% in
  2012-17 (version 6.2) and -1.1% in 2018-21 (6.03), a 1.6-point step that is the size of normal year-to-year noise.
  FRP shows no step (-0.1% vs -0.1%).
  - Versions are uniform across countries: 6.2 for 2000-2017, 6.03 for 2018-2022, 61.03 for 2023-2025. The only
    exception is a trickle of 6.03 rows before 2018 in Somalia and Morocco (about 10k Aqua and 6k Terra detections).
  - The 2023 change to 61.03 coincides with orbit drift, so the two effects cannot be separated. Aqua/S-NPP moved by
    less than 4% at that boundary.
- **Back-fill of Nov 2000-Jun 2002 (before Aqua) is usable.** Factors per region x calendar month were fitted on
  2003-12 and tested on 2013-19. Day counts: global bias +3.2%, nMAE 5.3%; regional median |bias| 4.3%, median nMAE
  9.9%. Errors are worst in SHSA (+18%) and EQAS (+22%) because the factor drifted over time there.
  Of the 20 Terra-era months, 2 must be excluded (2001-06, 2002-03) and 2 rescaled (2001-07, 2002-04).
- **Outages.** All the outages listed in CONTEXT.md appear in the data. Corrections to the list:
  - Terra Oct 2022 ends on 23 Oct, not 19 Oct.
  - Aqua Aug 2020 is a partial loss (counts at 22% of normal), not a blackout.
  - S-NPP 2022 has zero data only from 27 Jul to 10 Aug.
  
  Outages not on the list:
  - **Aqua 1-16 Apr 2022: zero detections.** Please check whether this is an archive gap.
  - Aqua 30 Jul-7 Aug 2002.
  - Terra 20-28 Mar 2002, 17-24 Dec 2003, 20-23 Dec 2008.
  - **S-NPP: 30 May-3 Jun, 10-16 Jul, 24-29 Jul and 3-6 Nov 2024, and 5-7 Jul 2025.**

## 2. What I built (in `rezultate/qc_stability/`)
| File | Contents |
|---|---|
| `outage_calendar.csv` | one row per gap, with evidence and whether it matches a known outage |
| `completeness_monthly.csv` | frac_days_ok, a coverage weight, and flag_month (ok/rescale/exclude) per month |
| `ratio_by_year.csv`, `fig_ratio_drift.png` | Aqua/SNPP, Terra/Aqua, Terra/SNPP x n_sum/frp_sum x D/N x region/GLOBAL x 2012-25: ratio, index vs 2012-19, % change |
| `drift_by_year.csv`, `fig_drift.png` | median local solar time per satellite x year x D/N x latitude band x hemisphere. Tropics, day: Aqua 13:36 (2012) -> 14:45 (2025); Terra 10:31 -> 09:24; S-NPP stable 13:28-13:31 |
| `terra_to_aqua_factors.csv`, `terra_to_aqua_validation.csv` | back-fill factors and their validation |

Reproduce from `harmonizare/work/qc_stability/`:
`python3 01_pass_points.py` (re-run until finished), then build `daily_all.parquet` (sum `pass1/*_daily.parquet` by
satellite, daynight, acq_date), then `02_outages.py`, `03_regional_monthly.py`, `05_ratio_drift.py`, `06_drift_lst.py`,
`07_terra_backfill.py`.

## 3. Method in plain words
- **Outages.** A day is flagged when it has zero detections, or fewer than 50% of its usual level. The usual level is the
  median of the surrounding ±15 or ±30 days. A low day only counts if it is also low compared with a partner satellite
  that was working normally that day.
- **Ratio index.** For each calendar month I take the 2012-19 ratio between the two satellites. From the second
  satellite's real count I compute an "expected" value for the first, and compare the yearly sum with that expectation.
  This way a missing month cannot fake a step. A month is used only if it is "ok" for both satellites.
- **Back-fill.** One Aqua/Terra ratio of sums per region x calendar month x day/night. Where Terra had fewer than 50
  detections in a cell, it falls back to the region's yearly factor.

## 4. Caveats
- The back-fill period lies before the fit period. In SHSA and EQAS the factor changed by about 20% within a decade, so
  their 2000-02 values carry uncertainty of that size. The CSV has an interannual CV column.
- The pooled-hemisphere local-time values are approximate: a weighted mean of the two hemisphere medians.
- Outage flags use UTC dates while the monthly tables use local dates, so months can differ by a day at the edges.
- I cannot tell whether the Aqua April 2022 gap is real or missing from the archive.
- Not done: the table sanity audit (deliverable 5) and the Terra high-latitude check.

## 5. Needed from the orchestrator
- Verify the Aqua April 2022 and S-NPP 2024 gaps against the NASA/NOAA event logs.
- Pass completeness_monthly to the agents building the final product (`exclude` = mask, `rescale` = divide by coverage).
