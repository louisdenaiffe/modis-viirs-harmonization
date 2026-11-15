# MODIS + VIIRS fire hot-spot harmonization — project summary

NASA Space Apps Challenge 2026 · track "Harmonization of MODIS and VIIRS Hot Spots" · branch `ianis_harmonization`, folder `harmonizare/`

This document explains what we built, why, how well it works and what its limits are. It is written so that a teammate (or an AI assistant) can read only this file and present the work.

---

## 1. The problem in one minute

Two NASA satellite instruments record active fires:

| | MODIS | VIIRS |
|---|---|---|
| Satellites | Terra (~10:30) and Aqua (~13:30) | Suomi NPP (~13:30) |
| Record | since Nov 2000 | since Jan 2012 |
| Pixel size | 1 km | 375 m |
| Status | orbits drifting; instruments near end of life | the continuation |

VIIRS has smaller pixels, so it reports far more detections for the same fires. If you simply add the two records together, fire activity appears to explode in 2012. Measured on our data:

| What VIIRS reports relative to MODIS Aqua, same fires | Day | Night |
|---|---|---|
| Number of detections | 5× | ~30× |
| Radiative power (FRP) | +27% | +129% |

The naive global record jumps by **×5.03** between 2011 and 2012. That jump is sensor physics, not fire. Without a correction, nobody can honestly compare a month in 2025 with the same month in 2005.

**Goal:** one continuous monthly fire-activity record, 2000–2025, for the whole globe, where the sensor change leaves no artificial step, with a stated uncertainty, ready for a web app (a "fire calendar": months × years, plus statements such as "this month is the record for this area since 2003").

---

## 2. What we delivered

1. A harmonized global record, Nov 2000 – Dec 2025, monthly, on a 0.25° grid (~28 km), day and night separately, for detection counts and for FRP.
2. The record on **two scales**, side by side in the same files:
   - **MODIS scale** ("what Aqua would have reported"): 2002–2021 are real measurements, the rest are converted.
   - **VIIRS scale** ("what VIIRS would have reported"): 2012–2025 are real measurements, 2000–2011 are converted from MODIS.
3. Ready-made tables per country (230) and per region (14 + global), with the rank of each month, a typical error and a confidence label.
4. A validation package: errors on held-out years, per region, per country, per rectangle size; a "famous fires" test; a benchmark kit to compare against another model.

After harmonization the 2011 → 2012 step is **×1.03** instead of ×5.03.

---

## 3. Data

- NASA FIRMS country archives, standard (science-quality) products, as CSV.
- MODIS Collection 6 / 6.1, Terra + Aqua, Nov 2000 – Dec 2025: about 113 million detections.
- VIIRS 375 m Collection 2, Suomi NPP only, 20 Jan 2012 – 31 Dec 2025: about 281 million detections.
- MODIS 2001 was missing from the team's download and was fetched from FIRMS.
- We did **not** use the Level-2 swath products (MYD14, MYD03, VNP14IMG, VNP03IMG). They carry cloud and coverage masks but are tens of GB per day; they were judged unnecessary for a two-day project. Consequence: a zero in our record means "no detection", not "certainly no fire".

---

## 4. Method, step by step

### 4.1 Cleaning
- Keep only FIRMS `type == 0` (presumed vegetation fire); volcanoes, static land sources and offshore sources are removed.
- Drop low-confidence detections (MODIS confidence < 30, VIIRS class `l`).
- **Static-source mask** (our own): 0.01° cells that burn all year (gas flares, refineries, steel plants) or are lava from eruptions, which the FIRMS flag misses. A cell is masked if it has a persistent FIRMS non-fire flag, or is active ≥ 16 days in ≥ 9 calendar months of a year, or is a night-dominated year-round source; recurring seasonal fires (crop residue, peat) are protected by the seasonality rule. The mask removes 0.2% of day detections and about 3% of night detections globally, but 52–61% of night detections in the Middle East.

### 4.2 A common unit
- Aggregate to 0.25° cells, per month, day and night separately.
- Harmonize **detection counts** and **FRP**, each with its own calibration.
- We tested "active days" and "active cells" (presence metrics). They were less stable between sensors (region-month error 16–33% versus 10–23%), so we dropped them.

### 4.3 Pair the right satellites
- VIIRS on Suomi NPP is compared with MODIS on **Aqua**: both pass at ~13:30 and ~01:30 local time.
- Terra passes at ~10:30, when fires are weaker, and has no VIIRS equivalent. It is used only to extend the record before Aqua existed.

### 4.4 Calibration (learned from the overlap years)
Calibrated on Feb 2012 – Dec 2017, all countries. Tested on 2018–2021, which were never used for fitting.

- **Day:** ratio of sums Aqua / VIIRS per region × season, multiplied by a per-cell adjustment. Cells with little data borrow from their 2° block and then from their region (shrinkage). At high northern latitudes (Canada, Siberia) day counts use only the strongest overpass per day, with separate factors above and below 60°N, because satellites overlap more often there.
- **Night:** weights per VIIRS pixel-power class. Reason: 80% of VIIRS night pixels are below 3 MW and MODIS sees about 1% of those, so one ratio cannot describe the night.
- This is a table of calibrated factors, **not** machine learning. We trained a gradient-boosted model (LightGBM) as a challenger: it was slightly better in regions it had seen, but 23–30% wrong in a region held out of training, so it was rejected.

### 4.5 Building the record
| Period | Source (MODIS scale) |
|---|---|
| Nov 2000 – Jun 2002 | Terra converted to Aqua-equivalent (factors per region × calendar month, fitted on 2003–2006) |
| Jul 2002 – Dec 2021 | real Aqua |
| from Jan 2022 | VIIRS converted to Aqua-equivalent |

- Months with a satellite outage are replaced by the other sensor; partially covered months are rescaled.
- The VIIRS scale is built the same way in reverse: real VIIRS from Feb 2012, converted Aqua (or Terra) before.

### 4.6 Why MODIS cannot simply continue
The MODIS orbits are drifting. Overpass time measured in our data: Aqua 13:37 → 14:55 (2025); Terra 10:28 → 09:14 (2025). Relative to harmonized VIIRS, daytime, global:

| | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| Aqua | within ±2% | within ±2% | within ±2% | within ±2% |
| Terra | −10% | −17% | −31% | −42% |

Anyone adding Terra + Aqua sees a "decline in fires" after 2021 that is an orbit artefact. Aqua is also affected regionally and at night by 2025.

---

## 5. How good is it?

All numbers are for 2018–2021 (held out), converted VIIRS against real Aqua, unless stated.

### 5.1 Systematic error (bias)
| | Global | Median region | Worst region |
|---|---|---|---|
| Counts, day | +2.6% | 2.1% | 6.1% |
| FRP, day | +1.6% | 2.9% | 8.4% |
| Counts, night | +1.6% | 5.5% | 31% |
| FRP, night | −2.3% | 3.3% | 34% |

Extra check on 2022–2023: day counts +1.4%, day FRP +0.7%.

### 5.2 Error of a single month (errors cannot cancel)
Bias lets positive and negative errors cancel, so it is not the error a user sees. For day + night counts:

| Area | Bias | Mean absolute monthly error | RMS monthly error |
|---|---|---|---|
| Globe | +2.6% | 4.3% | 5.4% |
| Countries with ≥ 1,000 detections/month (40) | 2.8% | 8.3% | 15% |
| Countries with 100–999 (35) | 4.3% | 15% | 26% |
| Countries with 10–99 (58) | 6.7% | 27% | 45% |
| Countries with < 10 (11) | 18% | 43% | 61% |

Per country, daytime: median bias 4.5%; 74% of countries within 10%, 91% within 20%.

### 5.3 Accuracy depends on how much fire is in the selected area, not on its size
| Detections per month in the area | Typical error | Confidence label |
|---|---|---|
| ≥ 1,000 | ~9% | high |
| 100–999 | ~14% | medium |
| 10–99 | ~25% | low |
| < 10 | no monthly number | show "few fires" or the annual total |

Annual totals are roughly one level better (6–7% at ≥ 1,000 detections per year).

### 5.4 The VIIRS scale (reverse conversion), region-month level
| | Bias | Mean absolute error | RMS error |
|---|---|---|---|
| Counts, day | 3.0% | 7.3% | 11.6% |
| FRP, day | 4.0% | 10.8% | 19.4% |
| Counts, night | 10.4% | 21% | 46% |
| FRP, night | 11.6% | 21% | 41% |

Day is as good as the MODIS scale. Night before 2012 is usable only as country or regional totals: in 86% of the cell-months where VIIRS sees fire at night, MODIS saw nothing, and zero times any factor is zero. **Converting to the VIIRS scale changes the unit, not the quality** of the old data.

### 5.5 Physical evidence: both satellites looking at the same fire
From overpasses less than 10 minutes apart (2015, 2019, 2021; 4.3 million fire clusters):
- MODIS misses 60% of the fires VIIRS sees by day (75% at night), but those hold only 33% (37%) of the power.
- MODIS has a 50% chance of detecting a fire from ~14 MW by day and ~9 MW at night; at the swath edge the daytime threshold rises to 32 MW (10 MW at nadir).
- When both see the fire, the power agrees (VIIRS / MODIS = 0.95 day, 0.94 night).
- No single power threshold on VIIRS reproduces MODIS for both counts and power, which is why the two are calibrated separately.

### 5.6 The "famous fires" test
30 documented fire events, checked in the harmonized record:

| Era | Events | Record month for their area | In the top two |
|---|---|---|---|
| MODIS era (to 2021) | 18 | 13 | 15 |
| VIIRS era (from 2022) | 12 | 8 | 10 |

None of 6 quiet control periods is flagged. In the naive record, ordinary recent summers outrank historic fires (Balkans July 2007 falls from 1st to 7th). The misses are real but moderate seasons (Amazon August 2019 ranks 9th of 23 because 2003–2010 burned more).

---

## 6. Known limits (say these before the committee asks)

- **Night values on small areas are weak**, on both scales.
- **Low-fire areas** (below ~100 detections a month) have monthly errors of 25% or more; show them with a low-confidence label or as annual totals.
- **One-off extreme seasons** unlike the calibration years can be off by up to ±40% in a small area.
- **Southern Africa, 2000–2002:** the Terra back-fill is probably ~20% too high (a step of −20% at mid-2002, outside the normal range of −11% to +13%). Cause not found; flagged.
- **A slow drift of about ±3%** in the ratio between the sensors cannot be corrected from the calibration years alone; it is stated as systematic uncertainty.
- **No cloud masks:** absence of a detection is not proof of no fire.
- **Daily values are not harmonized**, only monthly.
- **The static mask** was built from three sample years; eruptions and new flares outside those years can slip through.
- **The test years 2018–2021 were looked at several times** while choosing between variants, so they are not a perfectly untouched test; 2022–2023 is the cleaner check.
- **The record ends in Dec 2025.** Suomi NPP stopped delivering data in Nov 2026; continuing needs NOAA-20, which we did not include.

---

## 7. Files

Everything the app needs is in `harmonizare/APP_DATA/` (instructions in `CITESTE-MA-APLICATIE.md`, Romanian):

| File | Content |
|---|---|
| `cells_monthly/final_{year}.parquet` | per cell × month × day/night: `n_eq`, `frp_eq` (MODIS scale), `n_veq`, `frp_veq` (VIIRS scale), intervals, source of each value |
| `country_month.csv`, `region_month.csv` | aggregated tables with rank, anomaly versus the historical median, typical error and confidence |
| `country_season.csv`, `region_season.csv` | seasonal profile: normal level of each calendar month (median, mean, p10, p90) and its share of the year |
| `country_year.csv`, `region_year.csv` | yearly totals and the rank of each year |
| `country_trend.csv`, `region_trend.csv` | 2003–2025 trend in % per year with a significance test |
| `cell_country.parquet` | country of each grid cell |
| `accuracy_modis_scale.csv`, `accuracy_viirs_scale.csv` | error lookup by rectangle size and detection count |
| `famous_fires.csv`, `fig_harmonization_summary.png`, `fig_detection_curve.png` | demo and pitch material |

Other folders:
- `harmonizare/scripts/01…08_*.py`: the pipeline in run order (ingest → grid → monthly → evaluation → final record → summaries → mask → app package).
- `harmonizare/rezultate/*/REPORT.md`: detailed reports for each analysis (calibration, physics, quality control, static mask, events).
- `harmonizare/BENCHMARK/`: common truth table, scoring script and instructions for comparing our model with another one.
- `harmonizare/CITESTE-MA.md`: method notes in Romanian.

The app does no modelling at run time: it reads the column for the chosen scale and sums the cells inside the selected area.

---

## 8. How the work was done

- All data processing ran locally with DuckDB and Python on the raw CSVs.
- An AI orchestrator split the work into precise tasks for specialised AI agents (literature and sensor research, quality control, two calibration approaches, the simultaneous-overpass physics, the static mask, the event test) under one shared evaluation protocol, so every variant was scored the same way.
- Every method choice was made on calibration years and judged on held-out years; simpler methods were kept unless a more complex one won on held-out data.

---

## 9. How this maps onto NASA's own harmonization practice

NASA already harmonizes other sensor pairs. Two reference cases: **HLS** (Harmonized Landsat and Sentinel-2) and the **MODIS–VIIRS continuity products** for clouds and aerosols. Our pipeline follows the same logic, applied to fire detections.

| NASA practice | What it does there | Our equivalent |
|---|---|---|
| Remove effects that are not the signal (HLS: atmospheric correction) | both sensors measure the surface, not the air | keep vegetation fires only: FIRMS type flag, confidence filter, our static-source mask |
| Common grid (HLS: one 30 m tiling) | pixels from both sensors line up | one 0.25° global grid, monthly |
| Bring the finer sensor to the coarser one (HLS: Sentinel-2 10–20 m resampled to 30 m) | compare like with like | VIIRS 375 m converted to the MODIS scale as the reference record |
| Adjust one sensor to a reference sensor (HLS: Sentinel-2 bands adjusted to Landsat's response) | removes differences caused only by the instrument | VIIRS adjusted to Aqua with factors learned on the overlap years |
| View-geometry normalization (HLS: BRDF correction) | a change of viewing angle is not mistaken for a change on the ground | handled by monthly aggregation (all view angles are sampled) and, at high latitudes, by using the strongest overpass per day; measured but not corrected per detection |
| Pair sensors with the same overpass time (continuity products: Aqua MODIS + Suomi NPP VIIRS) | no time-of-day difference | Aqua paired with Suomi NPP; Terra used only before Aqua existed |
| Keep sensor identity and quality information with every value (HLS: separate L30 / S30 products, QA layer) | users know what they are looking at | `source`, `flag`, interval and confidence on every value |

Where NASA's approach differs from ours, and what it suggests:
- **Same algorithm on both sensors.** The continuity products run one shared algorithm on MODIS and VIIRS, so the retrieval method drops out of the comparison. For fire, the equivalent is NASA's VIIRS 750 m active-fire product, which uses the MODIS-heritage algorithm. We instead calibrate the outputs of two different algorithms. Comparing our converted values with the 750 m product would be a strong independent check (not done).
- **Per-observation view-angle correction.** HLS normalizes each observation to a standard geometry. We measured the effect (MODIS detects from ~10 MW at nadir but ~32 MW at the swath edge) and let monthly aggregation average it out. A per-detection correction is the natural next refinement, and what a daily product would need.
- **Morning orbit.** NASA states there is no VIIRS replacement for Terra's morning overpass. Our record is anchored on the afternoon orbit for exactly this reason.

Sources: https://www.earthdata.nasa.gov/data/projects/hls · https://hls.gsfc.nasa.gov · https://atmosphere-imager.gsfc.nasa.gov/continuity/products · https://atmosphere-imager.gsfc.nasa.gov · https://www.earthdata.nasa.gov/news/blog/from-modis-viirs-continuing-legacy · https://www.earthdata.nasa.gov/data/alerts-outages/modis-viirs-transition

---

## 10. Suggested pitch (five slides)

1. **The problem:** the naive record jumps ×5 in 2012; MODIS is ending; Terra has already lost 42% of its detections to orbit drift.
2. **The idea:** learn the conversion from six years when both sensors watched the same fires; verify on years the model never saw.
3. **The proof:** the step falls from ×5.03 to ×1.03; global monthly error ~4–5%; 91% of countries within 20%; figure `fig_harmonization_summary.png`.
4. **Reality check:** 21 of 30 famous fires are the record month for their area, in both sensor eras; no false alarm on quiet periods.
5. **Honesty and product:** every value carries its source and a confidence level; the app shows both scales and warns when an area has too few fires for a reliable number.

## 11. Questions the committee may ask

- *Why not machine learning?* We tried it; it failed on a region it had not seen (23–30% error). Calibrated factors are explainable and generalise.
- *Why the MODIS scale and not VIIRS?* We provide both. On the MODIS scale most of the 26 years are real measurements; the VIIRS scale matches today's data. Month rankings are nearly identical.
- *How do you know it is right?* Held-out years, a later independent period, per-country errors, simultaneous-overpass physics and the famous-fires test all agree.
- *Where does it fail?* Night on small areas, low-fire areas, one-off extreme seasons. The app labels these as low confidence.
- *What happens after 2025?* NOAA-20 and NOAA-21 carry the same instrument; the same method applies with one extra calibration step.

---

## 12. Status against the challenge text, and what to do next

### 12.1 Checklist
| What the challenge text asks for | Status |
|---|---|
| Harmonize so that "the sensor of origin no longer matters" | Done: one record; the source is kept only as a label |
| Calendar of hotspot counts "from the early 2000s to the present" | Done to Dec 2025; **2026 is missing** |
| "Which month and years had the highest fire activity" | Done: rank of every month (`*_month.csv`) and of every year (`*_year.csv`) |
| "Compare the burning activity of the current month against the historical median" | Done: `median_*` and `anom_pct_*` columns |
| "Which periods of the year see more fires" | Done: seasonal profile (`*_season.csv`) |
| "Historical comparisons, including anomalies against multi-year averages" | Done: `mean_*`, `anom_pct_*` |
| "Patterns, trends, and anomalies" | Done: `*_trend.csv` (global trend 2003–2025: −0.9% per year, significant) |
| Select a region (draw on a map, or enter latitude/longitude) and a date range | App work; the cell data supports any rectangle |
| Download analytics and visualizations | App work |
| "Downloadable CSV of hot spots detected during a search" | **Open**: needs the individual detections (see 12.2) |
| Accessible color ramps | App work |

### 12.2 Open gaps
1. **"To the present" / "current month".** The record ends in December 2025. For the demo this is defensible, but it is the gap a judge is most likely to notice.
   - Minimum: say it in the pitch. New months go through the same factors; after November 2026 the input becomes NOAA-20, which needs one extra calibration step (NOAA-20 to Suomi NPP).
   - Better: download the 2026 Suomi NPP detections from FIRMS (January to October) and run them through the same pipeline; the calendar then reaches October 2026.
2. **CSV of hotspots for a search.** This means individual detections, not monthly cells. The raw FIRMS CSVs are on the team's disk; a fast Parquet copy can be rebuilt with `scripts/01_ingest.py` (about 10 minutes, ~9 GB). The app can serve either that file or the FIRMS CSVs directly.

### 12.3 Advice for the app
- **No modelling at run time.** Both scales are precomputed columns. The app reads the column for the chosen scale and sums the cells in the selected area. There is no ML model to load.
- **Show the monthly total (day + night) by default.** Offer a night-only view only where the area has at least ~100 night detections a month; night-only values are the unreliable ones (example: China is +85% wrong at night but +2% on the day + night total).
- **Show a confidence label from the number of detections in the selected area that month**: ≥ 1,000 high (~9% typical error), 100–999 medium (~14%), 10–99 low (~25%), below 10 no monthly number ("few fires", or show the annual total).
- **Hide the "record month" badge below ~50 detections.** With tiny numbers a record is noise (Maui 2023 is a "record" with 17 detections).
- **VIIRS scale, night, before 2012:** show numbers only for countries or regions, not for small rectangles.
- **For points on the map, use the original FIRMS detections.** The harmonized files are for the calendar and the statistics.
- **Smallest useful area:** one grid cell is ~28 km. In fire-prone regions a rectangle of 50–100 km usually has enough detections for a medium or high confidence; in Europe it often takes a country, or annual totals instead of monthly.
- **"Top 5%" with 23 reference years means rank 1; "top 10%" means rank 1–2.**

### 12.4 What we decided not to do, and why
- **Level-2 swath products (cloud and coverage masks):** tens of GB per day and heavy processing; not needed for monthly values.
- **Machine learning in the final record:** tested, lost on unseen regions.
- **Cross-check against NASA's 750 m VIIRS fire product, and per-detection view-angle correction:** scientifically sound next steps, but the challenge text does not ask for them and they would not change the app.
- **NOAA-20 / NOAA-21:** needed for data after November 2026; left out because the demo ends in 2025.
- **Daily harmonized values:** not validated; monthly is what the calendar needs.

### 12.5 Comparing with the other team model
`harmonizare/BENCHMARK/` contains a common truth table (real VIIRS, 2018–2023), our MODIS-only predictions and one scoring script for both models. Rules: neither model may have seen the test years; predictions must come from MODIS only; both are scored on the same countries; decide on absolute and RMS errors, not on bias. Details in `BENCHMARK/BENCHMARK.md`.
