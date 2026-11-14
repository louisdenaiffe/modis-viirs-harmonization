# Shared context for all agents — MODIS/VIIRS hot-spot harmonization (NASA Space Apps, 14-15 Nov 2026)

## Goal
A 2000-2025 fire-activity record with no artificial step where MODIS hands over to VIIRS, on a 0.25 deg grid,
monthly (daily for display), expressed in **Aqua-MODIS-equivalent** units, separately for day (D) and night (N),
with uncertainty and provenance, validated on held-out overlap years. A web app (fire calendar + anomaly
statements like "top 5% since 2003") will sit on top. The team are students, not fire scientists: every
deliverable must be explainable in plain words and reproducible with one command.

## Where you work (IMPORTANT, read fully)
- All data is on the user's computer. Use the `mcp__remote-devices__device_bash` tool (load it with ToolSearch
  `select:mcp__remote-devices__device_bash` if it is not loaded). The cloud `Bash`/`Read`/`Write` tools CANNOT see this data.
- Project folder inside that shell: `cd "$HOME/mnt/"NASA*/` (folder name has spaces and a trailing space; always quote).
  Everything lives in `harmonizare/` under it.
- Each device_bash call is a fresh shell, hard limit 180 s, and background processes are killed when the call returns.
  Design every script to finish in <150 s or to be resumable (process year by year, skip finished outputs).
- Machine: 4 cores, 3 GB RAM, shared with 4 other agents. In DuckDB ALWAYS:
  `SET memory_limit='600MB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='harmonizare/data/_ducktmp/<your_name>'`
  Never load a whole points file into pandas; aggregate in DuckDB first. If you get OOM, lower memory use, retry.
- Python 3.10 with duckdb, pandas, numpy, pyarrow, scipy, scikit-learn, lightgbm, matplotlib, h3 installed. `pip install` works. Internet works.
- Write ONLY inside `harmonizare/work/<your_name>/` (scripts, intermediates) and `harmonizare/rezultate/<your_name>/`
  (deliverables: REPORT.md, CSV/Parquet, PNG figures). Never modify the raw CSV folders, `data/points`, `data/grid`,
  or `scripts/` (ask the orchestrator in your report instead). Delete only files you created.
- To look at a PNG you made you cannot view it from the device; trust numeric checks (print the plotted values).

## Data (already built)
- `data/points/{modis|viirs}_{year}.parquet` — every FIRMS detection, 400M rows total. Columns: sensor, satellite
  (Terra, Aqua, SNPP), country, lat, lon, acq_date, hhmm, ts (UTC timestamp, minute precision, true scan time),
  lst (local solar hour), daynight (D/N), scan, track (pixel size km), frp (MW), bt_fire, bt_bg, conf_raw,
  conf_class (l/n/h; MODIS <30 = l, 30-79 = n, >=80 = h), version, type (0 vegetation, 1 volcano, 2 static land,
  3 offshore), ix, iy (0.25 deg cell: lon = (ix+0.5)*0.25-180, lat = (iy+0.5)*0.25-90), sx, sy (0.01 deg cell).
  MODIS 2000-11..2025-12 (versions 6.2 / 6.03 = Collection 6, 61.03 = Collection 6.1 for 2023+). VIIRS = S-NPP only,
  2012-01-20..2025-12-31, version 2. No duplicate rows across country files (checked).
- `data/grid/op_{modis|viirs}_{year}.parquet` — one row per satellite overpass per 0.25 deg cell (detections <=20 min
  apart = same overpass): t_start, ldate (local date), daynight, lst, n_all, frp_all, n0/frp0 (type 0),
  **n0q/frp0q (type 0 and confidence not low — the default filter)**, n_volc, n_static, n_offshore, n0_low, n0_high,
  nsub0q (distinct 0.01 deg sub-cells), scan_mean, scan_max, frp_max, and FRP-binned counts/sums for the default
  filter: c_lt3, c_3_6, c_6_10, c_10_20, c_20_50, c_ge50 and f_* (MW).
- `data/grid/monthly_025/monthly_{year}.parquet` — monthly per cell x satellite x daynight (year/month from local date):
  n_sum, frp_sum (plain totals, default filter), n_best, frp_best, nsub_best (strongest overpass per day only),
  days (active days), ops, n_all, n0, n0_low, n_static, n_volc, n_offshore, scan_mean, lst, c_*/f_* bins.
- Scripts that built them: `scripts/01_ingest.py`, `02_grid.py`, `03_monthly.py` (read them for exact definitions).

## Shared evaluation protocol (mandatory for any model that predicts Aqua-equivalent values)
`scripts/eval_common.py` — read its docstring. Target = Aqua `n_sum` and `frp_sum` per cell-month-daynight.
Calibrate ONLY on 2012-02..2017-12. Test on 2018-01..2021-12 (Aug-Sep 2020 excluded). Never tune on the test period.
Call `ec.evaluate(pred_df, '<label>', notes=...)`; it appends to `rezultate/leaderboard.csv`. Current baselines:
- M0 raw VIIRS as MODIS: counts +401% (day), +2863% (night); FRP +26% (day), +126% (night).
- M1 one global ratio per day/night (counts D 0.204, N 0.034; FRP D 0.795, N 0.414): global bias ~2% but
  median regional |bias| 13% (day counts), worst region 37%; night worst region 126%; tercile agreement 0.67 (day).
Regions = coarse GFED-like boxes in `eval_common.REGIONS`.

## Facts already established (do not re-derive unless your task says so)
- Orbit drift measured in this data (median local solar time of daytime detections): Aqua 13:37 stable 2002-2021,
  then 13:41 (2022), 13:55 (2023), 14:19 (2024), 14:55 (2025). Terra 10:28 stable to 2020, 10:24 (2021), 10:16 (2022),
  10:02 (2023), 09:42 (2024), 09:14 (2025). S-NPP stable 13:37. So MODIS is NOT a stable reference after 2021.
- Known outages: Terra 15 Jun-2 Jul 2001, 19-27 Feb 2016, 10-19 Oct 2022, loss of high-latitude daytime coverage
  since Oct 2020; Aqua 16 Aug-2 Sep 2020; S-NPP 26 Jul-20 Aug 2022; S-NPP ended for good on 2 Nov 2026
  (NOAA-20/21 continue the afternoon orbit; nothing replaces Terra's morning orbit).
- VIIRS FRP comes from the 750 m M13 band and is split evenly among the 375 m fire pixels inside it, so summing
  per-pixel FRP is valid; frp = 0 can mean M13 saturation (missing, not zero).
- VIIRS `type` flag in archive version 2 is reported to be buggy (many static sources labelled 0; fixed in v3,
  May 2025). Our VIIRS files are version 2.
- Literature (Li et al. 2018 JGR; Li et al. 2020 RS 12,1561; Fu et al. 2020 RS 12,2870; RS 2026 18,1650;
  GFED5NRT Chen et al. 2026 ESSD; QFED 3.2): count ratios VIIRS/MODIS vary ~1.7x to 6x by region; summed FRP agrees
  within ~+-20% in most biomes; MODIS min FRP ~2.5-4 MW at nadir -> 17-34 MW at swath edge, VIIRS ~1.5-3.6 MW;
  MODIS inter-scan (bow-tie) duplicates ~10% of counts; standard practice = stratified ratio-of-sums by
  region x land cover (GFED5NRT), linear regression by biome (QFED), VZA-polynomial FRP correction (RS 2026).

## Report format (your final message AND `rezultate/<your_name>/REPORT.md`, English, <= 600 words)
1. Answer first: the 3-5 findings that change what the team should do, each with its number.
2. What you built (file paths + one-line description + the command to reproduce).
3. Method in plain words. 4. Caveats/what you could not verify. 5. Anything you need from the orchestrator.
State clearly what is measured vs assumed. Do not claim something works unless a number in your report shows it.

## UPDATE 14 Nov, afternoon (read this — it overrides the sections above where they differ)
- Disk was cleaned at the user's request. `data/points` now holds ONLY 2015, 2019, 2021 (both sensors). `data/grid/op_*.parquet`
  are DELETED. `data/grid/monthly_025/` (monthly table, all years) is intact. Raw CSVs are intact in `../MODIS data` and `../VIIRS data`
  (DuckDB reads one VIIRS year of CSVs in ~30 s if you truly need another year: see scripts/01_ingest.py for the read_csv call).
- Real per-call limit is ~125 s: keep every device call <= 100 s. Compute and disk are scarce: new files < 50 MB per agent unless
  told otherwise, delete your intermediates and your `data/_ducktmp/<name>` when done. Write REPORT.md early, update it as you go.
- The production record EXISTS: `rezultate/final/parts/final_{year}.parquet` (cell-month-daynight: n_eq, frp_eq, lo/hi, source, flag),
  `rezultate/final/region_month.csv`, built by `scripts/04_build_final.py` + `05_summaries.py`.
  Recipe: DAY = calib_ratio B5 (`rezultate/calib_ratio/apply_model.py`: region x season ratio x shrunk cell factor, separate factors for
  counts and FRP); NIGHT = calib_physics_ml P1 (`rezultate/calib_physics_ml/apply_model.py`, counts='p1': weights per VIIRS FRP class,
  separate for counts and FRP). Splice: Terra back-fill < 2002-07, real Aqua 2002-07..2021-12, converted VIIRS from 2022-01;
  months flagged in `rezultate/qc_stability/completeness_monthly.csv` are swapped/rescaled.
- Measured so far (test 2018-2021, vs real Aqua): global bias +3.0% day counts, +1.6% day FRP, +2.6% night counts, -4.0% night FRP;
  regional median |bias| 3.0% day / 5.6% night counts; worst regions BONA day +12.7%, night about -25%; MIDE/CEAS night +20-35%.
  Accuracy depends on activity: >=1000 Aqua-eq detections/month ~+-10%, 100-999 ~+-15%, 10-99 ~+-25-35%.
- No static-source mask has been applied yet (only FIRMS type == 0 and confidence not low).
