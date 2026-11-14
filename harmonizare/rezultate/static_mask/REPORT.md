# static_mask — static sources (flares, industry, volcanoes) in the MODIS/VIIRS record
All numbers are measured on 2015+2019+2021 under the default filter (type 0, confidence not low), unless marked otherwise.

## 1. Answer first
1. **The FIRMS type flag already removes most static sources.** At night, type 2 is 17-21% of Aqua and about 20% of S-NPP detections. The remaining contamination inside type 0 is small worldwide: S-NPP **4.1% of night counts (5.8% FRP), 0.22% of day counts**; Aqua **3.1% night (4.0% FRP), 0.20% day**; Terra 1.7% night, 0.6% day. **The ~28x night VIIRS/Aqua ratio is not caused by static sources**: masking moves it from 28.43 to 28.13 (-1.1%). The day ratio does not change (4.978 to 4.977).
2. **The contamination is large in some regions, and it hits the two sensors differently.**
   - MIDE: inside the mask are **61% of Aqua and 52% of S-NPP night detections**, and 6.6% / 14.3% of day detections. Masking moves the S-NPP/Aqua ratio **+21% (night) and -8% (day)**.
   - CEAS night: 10.5% Aqua vs 21.8% S-NPP, ratio **-12.7%**.
   - EURO night: 12.5% vs 15.5%, ratio -3.4%.
   - TENA night: 2.8% vs 7.5%, ratio -4.8%.
   - Every other region changes by less than 4%.
   MIDE and CEAS are exactly the regions where the production record has a night bias of +20-35%.
3. **FIRMS also flags real fire as static.** In Indonesia in Sep-Oct 2015, MODIS labelled 14,054 peat-fire detections type 2. That is about 12% of the MODIS type-0 detections there (approximate). VIIRS lost under 1% the same way. So the default filter already drops part of the 2015 peat fires from MODIS but not from VIIRS. For that reason my mask uses type 2/3 flags only when they appear in **at least 6 different calendar months**.
4. **Lava from new eruptions comes through as type 0.** Examples: La Palma 2021 (12,847 S-NPP type-0 detections, none flagged by FIRMS), Fagradalsfjall 2021, Holuhraun 2015. These are the top sites in `top_static_sites.csv`, and I added them by hand from a list of eruptions. Eruptions outside the 3 sample years (Kilauea 2018, Reykjanes 2023-25, ...) are **not** in the mask.
5. **Recommendation: (b) subtract the mask in every year, and also (a) flag cells where static sources make up at least 50%.** Subtracting costs essentially nothing in fire regions: masked share is S-NPP Punjab 0.19%, Amazon arc 0.20%, Sahel 0.08%, NE China 0.70%, Indonesia 1.44% (mostly Bontang LNG and oil fields; their detections span every month and 2-3 years). It also removes the sensor-asymmetric bias in MIDE and CEAS. Cells to flag: 3,471 of 72,088 S-NPP night 0.25° cells, and 344 of 11,547 Aqua night cells.

## 2. What I built (`rezultate/static_mask/`)
- `static_mask_001.parquet`: sx INT, sy INT, reason VARCHAR, (sx, sy) unique. 101,877 cells, of which 20,441 are core cells and the rest buffer. Core cells by reason: type_flag_viirs 14,700, type_flag_modis 2,308, persistence 1,906, volcano 999, offshore 528.
- `cell_static_share.parquet`: ix, iy, satellite, daynight, n_total, n_static, frp_total, frp_static, static_share_n, static_share_frp (3 years summed).
- `impact_by_region.csv` and `ratio_snpp_aqua.csv`: the impact tables. `type_shares.csv`: type shares by satellite, day/night and year.
- `tradeoff.csv` and `tradeoff_persistence.csv`: removal by threshold choice.
- `top_static_sites.csv` (30 sites with likely identity) and `top_volcano_cells.csv` (15 type-1 sites).
- `fig_static_map.png`. Plotted values: core cells per reason as listed above; 0.25° S-NPP night cells by static share: 50-80% = 1,341, at least 80% = 2,130, under 50% = 68,617.
- To reproduce, from the project folder: `bash harmonizare/work/static_mask/run_all.sh` (scripts 01-09 are in `work/static_mask/`).

## 3. Method in plain words
Each 0.01° cell is masked if any of these holds:
- **(R1) FIRMS flag:** at least 3 type 1/2/3 detections in either sensor. Volcano flags always count. Static-land and offshore flags count only if they appear in at least 6 calendar months.
- **(R2) Year-round type 0:** detected on at least 16 days and in at least 9 calendar months in one satellite-year, in 2 of the 3 years.
- **(R2b) Night-dominated type 0:** at least 16 days, at least 4 months, at least 2 months in each half of the year, and at least 90% of detections at night, in one year. This catches flares that FIRMS labels type 0 (Permian, Bakken, Iraq, West Siberia).
- **(R3) Known 2015/2021 eruptions.**

Every masked cell also masks its 8 neighbours (the buffer). Why: around 16,012 strong VIIRS static cell-years, the number of type-0 detections per cell falls from 7.2 (centre) to 2.1 (ring 1), 0.83 (ring 2) and 0.53 (ring 3), and 84-88% of them are at night (the S-NPP average is 25%). The buffer adds 0.84 percentage points to the S-NPP night share removed, but only 0.09 points to the day share.

The seasonality rules protect peat: persistent cells active in 3 months or fewer (Indonesian peat, California 2021) are 76% night-dominated, so a rule based only on night share would have masked them.

## 4. Caveats
- The mask is built from 3 years only, so flares or industry that started or stopped outside them are missed. Some suspects are still unmasked, roughly 1% of S-NPP night counts.
- Site identities come from coordinates and my own judgement; I checked none against a catalogue. One site (Veracruz, 18.5N 96.1W) is uncertain.
- Months come from the UTC date. VIIRS night has almost no low-confidence detections (0.0%), so the confidence filter does nothing there.
- `02_grid.py` removes every detection in a masked cell, so the type 1/2/3 columns lose counts too.
- By design, the default filter drops type 1 and type 3 in both sensors.

## 5. Needed from the orchestrator
The `op_*.parquet` files and the points for the other years are deleted, so re-gridding with the mask means ingesting the raw CSVs again. A cheaper option: multiply monthly n/frp by (1 - static_share) from `cell_static_share.parquet` per cell, satellite and day/night, and re-fit the day/night calibration for MIDE, CEAS and EURO.
