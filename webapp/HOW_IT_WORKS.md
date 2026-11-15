# Fire Globe: what it does and how it was built

A web app for the NASA Space Apps 2026 challenge "Harmonization of MODIS and VIIRS Hot Spots".
You spin a globe, draw a rectangle, and get a burning-activity calendar for that area from
2000 to today, with MODIS and VIIRS merged into one comparable record, shown either as VIIRS or
as MODIS would have counted it.

## The one-minute explanation

1. **Data.** NASA FIRMS publishes every fire hotspot its satellites detect. We use two
   sensors: MODIS (on the Terra and Aqua satellites, since November 2000) and VIIRS (on the
   Suomi NPP satellite, since January 2012).
2. **Problem.** VIIRS has sharper eyes (375 m pixels against 1 km), so it reports roughly
   3 to 4 times more hotspots than MODIS for the same fires. Putting the two records end to
   end shows a fake jump in 2012.
3. **Harmonization.** The team built two conversion models on the years when both sensors flew
   together. One turns MODIS counts into the number VIIRS would have reported (used before
   2012); the other turns VIIRS counts into the number MODIS on the Aqua satellite would have
   reported (used from 2022, when Aqua's orbit drifts). A switch shows the whole record on
   either scale: "VIIRS-equivalent" or "MODIS Aqua-equivalent" hotspots.
4. **App.** The page reads the prepared data directly in the browser (no server), adds up
   the hotspots inside your rectangle (or country) per month, and shows a calendar, an anomaly
   view, three charts, a month-by-month fire map and download buttons.

## Step by step

### 1. The globe (`index.html`, `app.js` sections 1-2)
- **MapLibre GL JS** (open source) draws the 3D globe. A copy is stored in `vendor/`.
- **Esri World Imagery** provides the satellite pictures, down to about 0.6 m per pixel.
- The stars are random dots drawn on a canvas behind the globe.
- Zoom speed is set to about 3 times MapLibre's default.
- **Two satellites** circle the globe on tilted, invisible orbits: detailed vector drawings
  of an Earth-observing satellite (shaded silver cylinder, dark sensor dish in front, copper
  engine nozzle behind, two long blue solar wings on a mast). They are drawn on a see-through
  canvas above the map that ignores clicks, hide behind the globe on its far side, and fade
  out when you zoom in close to the ground.
- The results panel is "frosted glass": semi-transparent with a blur of the globe behind it.

### 2. Selecting an area (`app.js` section 3)
- Hold **Shift and drag**, or press **Select** and drag (one finger on a touch screen).
- The rectangle is defined by two latitudes and two longitudes, and its edges are drawn
  with many intermediate points, so it lies on the curved surface.
- Minimum size is 375 m x 375 m (one VIIRS pixel). There is no maximum.
- Orange corner dots resize it; exact coordinates can be typed in the panel.

### 2b. Selecting a whole country (Shift + click)
- Hold **Shift and click** (without dragging) on a country, or on a phone press **Select** and tap it: its border is outlined and
  the panel shows the hotspots inside that border. A plain click elsewhere deselects it.
- Borders come from Natural Earth 1:50,000,000 (public domain), stored in
  `geo/countries.json` (242 countries).
- How it counts: the border is indexed by thin latitude bands (0.02°). Map squares fully
  inside the border use their stored monthly totals; squares crossed by the border are
  read hotspot by hotspot and each point is tested against the border.
- Checked: identical to testing every hotspot one by one (Argentina, Portugal, Fiji), and
  Argentina matches NASA's own Argentina file to 99.94% (the small gap is the difference
  between NASA's border and Natural Earth's).

### 3. Preparing the data (`tools/build_world.py`; the first Argentina-only version is `tools/legacy/build_tiles.py`)
Run once, in Python, with no extra packages. The text below describes the first Argentina-only
version; the world version (section 10) works the same way with finer squares where fires are dense:

    python3 -I tools/legacy/build_tiles.py data/raw/argentina data Argentina   (first version; the world uses tools/build_world.py)

- Reads the FIRMS CSV files (4.6 million hotspots for Argentina, 2000-2025).
- Cuts the world into **1 degree x 1 degree squares ("tiles")** and writes one small
  binary file per square (`data/tiles/`), 13 bytes per hotspot.
- Writes `data/index.json`: the monthly totals of every square, per satellite, plus the
  harmonization ratios.

Why: a browser cannot search millions of CSV rows each time. With tiles, squares fully
inside the rectangle are answered instantly from the index, and only squares cut by the
rectangle's edge are downloaded and checked hotspot by hotspot. The result is exact.

### 4. The harmonization (prepared by `tools/build_world.py`, added up in `app.js`)
The app shows the whole record on one of two scales, chosen with the **VIIRS / MODIS switch**
(bottom-left bar and results panel, kept in step). Each scale comes from one of the team's two
models. Both models work on a grid of 0.25 degree cells, month by month, day and night
separately. The data build turns them into a **weight for every hotspot** on each scale, and
the app only adds weights up. So a rectangle or a country of any shape gets the models' own
numbers, and a cell's total is spread over the hotspots really detected in it.

**VIIRS scale: "what VIIRS (375 m pixels) would have counted".**
- From February 2012: the VIIRS count itself. Each VIIRS hotspot weighs 1.
- Before February 2012: MODIS (Terra and Aqua; Terra alone before July 2002) converted to VIIRS
  by Louis's MODIS-to-VIIRS model (`glm_cell` on hotspot counts, METHOD.md section 6.10 in the
  repository). The model gives the VIIRS-equivalent count of every cell, month and day/night;
  the table is `tables/viirs_scale_cells.parquet`.
- That model is fitted on vegetation-fire detections of nominal or high confidence (FIRMS
  type 0). The other MODIS detections (low confidence, static sources such as gas flares) are
  converted with the VIIRS / MODIS ratio of their 1-degree square and month of the year,
  measured on the same kind of detections over the years both sensors flew. Where a square has
  few of them, its ratio leans toward its 10-degree block's and the world's (K = 20).
- Measured on a build of 2000-2024 (whole world): 20 to 24 million VIIRS-equivalent hotspots a
  year for 2003-2011, against 17 to 22 million counted by VIIRS a year for 2013-2023. For every
  hotspot Aqua saw, that is 6.7 to 6.9 VIIRS-equivalent hotspots in every year of 2003-2011,
  and 6.8 to 7.1 VIIRS hotspots in 2013-2019: no step at 2012.

**MODIS scale: "what MODIS on the Aqua satellite (1 km pixels) would have counted".**
This is Ianis's VIIRS-to-MODIS model (branch `ianis_harmonization`, `harmonizare/APP_DATA`).
- July 2002 to 2021: Aqua's own counts (with his corrections: months with missing days are
  rescaled, and sources that never move, such as gas flares, are masked). Terra hotspots do not
  count on this scale.
- Before July 2002: Terra converted to Aqua.
- From 2022, when Aqua's orbit drifts: VIIRS converted to Aqua.
- Months after the last one in his tables (they stop in December 2025): each VIIRS hotspot is
  weighted by the Aqua-equivalent / VIIRS ratio of its 1-degree square for that month of the
  year, day and night apart, measured on his 2022-2025 values (same leaning toward the block and
  the world). On VIIRS outage days Aqua's own hotspots count instead. This is a stopgap until
  his tables are extended. Tested by hiding his 2024 and 2025 tables on five countries: 2024
  came out 9% below his own 2024 values (2% to 12% depending on the region).

On the fire map both scales share one colour scale (taken from the VIIRS-scale map): on the
MODIS scale the map turns visibly dimmer, showing how much less the 1 km sensor detects, and
where.

Checked on a build of 2000-2024 (370 million hotspots):
- A selection made of whole 1-degree squares gives exactly the models' totals. A selection that
  cuts squares differs from them by 0.1% at most in a month (five rectangles tested, months of
  more than 50 hotspots), because the per-cell series of busy squares are stored rounded.
- Brazil on the MODIS scale: within 0.2% of Ianis's own country table over the whole record
  (the small gap comes from the border: he assigns whole 0.25 degree cells to a country, the
  app cuts along the border).
- 0.03% of the MODIS-scale total and 0.002% of the VIIRS-scale total before 2012 sit in cells
  where this build has no hotspot to carry them (small differences between the builds' input
  files); they are left out.

Limits to be honest about: both models are statistical. They assume the VIIRS/MODIS relationship
of the years both sensors flew also holds outside them, and they are far more reliable on a
country or a large region than on a few cells: a small rectangle can be off by tens of percent.
The two scales count slightly different things: the MODIS scale leaves out static sources and
Terra, the VIIRS scale keeps every detection. And the two models do not agree everywhere: the
VIIRS-scale / MODIS-scale ratio of a country can differ by 10 to 15% between 2003-2011 and
2013-2021 (Brazil 6.1 then 6.9, Russia 8.7 then 10.2; Australia 8.9 then 8.8).

### 5. The panel (`app.js`)
- **Calendar:** years as rows, months as columns, in the units chosen (VIIRS or MODIS). The
  colour runs from dark red (few hotspots) through orange to yellow (many), on a log scale.
- **Click a month** (a table cell, or a point on the Monthly record chart) to show it on the
  fire map, in the same units. The fire-map bar then reads the selected area's own count and
  how it compares with the same month in the other years (the Anomaly view's number, e.g.
  "Brazil 678,153 · +56% vs a usual September"), then the world's count, the units, and where
  the number comes from (VIIRS data, MODIS data, or one converted to the other). The cell of the month on the
  map stays outlined. On a phone the results slide away so the globe and the bar show;
  "Show results" brings them back.
- **Anomaly view:** each month compared with the median of the same month across the
  chosen years. Blue = below normal, grey = normal, red = above normal.
- **Headline figures:** total, most active year, peak month of the season, latest month
  against its median.
- **Margin of error** (thin green box under the figures): only the part of the total converted
  from the other satellite can be off; measured months carry no conversion error. Each year's
  converted part gets the typical yearly error found by the team's model tests, by how active
  the year is (VIIRS scale, Louis's leave-one-year-out test: 4.1% from 10,000 hotspots a year,
  6.1% from 1,000, 9.2% below; MODIS scale, Ianis's accuracy table: 4.4%, 6%, 11%, 23%, 55% for
  10,000+, 1,000+, 100+, 10+, fewer). The errors are added as if they never cancel out, so the
  ± is on the cautious side. Hovering the box shows the typical error of the converted part.
- **Gas-flare warning** (thin red box, only when it matters): `geo/static_sources.json` lists
  the 0.25° squares with steady heat sources (gas flares, refineries, steel plants, volcanic
  lava) from Ianis's static-source mask (`APP_DATA/cell_static_share.parquet`, Aqua + Terra +
  S-NPP, 2015, 2019 and 2021). The squares inside the selection are compared with all hotspots
  measured there in those years; the box shows when they are at least 1% (and 20 hotspots).
  They are still included in the counts. Sources that only existed in other years are missed.
- **Charts:** unusual years, monthly record, fire season with its critical period (table in
  section 11).
- The date range is chosen month by month (From / To), or with **Last 12 months** / **All**.
- **Unfinished month left out:** when the newest data stops in the middle of a month (FIRMS
  data for November 2026 runs to the 14th), that month is hidden everywhere (map, table,
  charts, figures, downloads) until it is complete; the record ends with the last full month.

### 6. Downloads (`app.js`)
- **Monthly table (CSV):** original MODIS, original VIIRS, VIIRS-equivalent and MODIS Aqua-equivalent value for every month, and where each comes from.
- **Hotspots in this search (CSV):** one row per detection (latitude, longitude, date, satellite, confidence, fire power, day/night, and what it counts for on each scale) for the area and dates chosen. It is written piece by piece straight to disk, with a limit of 3 million rows; above that the app explains and offers the largest recent date range that fits.
- **PNG:** the calendar and the charts as one picture.

### 7. The current year (`tools/legacy/fetch_nrt.py`, then `tools/fetch_nrt_world.py`)
NASA's yearly archive files stop at the end of last year. For 2026 the script asks the
FIRMS API (which needs a free key, stored in `.firms_key`, never shared) for every 5-day
window since 1 January, inside a rectangle around Argentina, and keeps only the points
inside Argentina's border (outline from Natural Earth, public domain). It takes
science-quality data as far as it exists and near-real-time data for the latest weeks.

    python3 -I tools/legacy/fetch_nrt.py data/raw/argentina 2026
    python3 -I tools/legacy/build_tiles.py data/raw/argentina data Argentina   (first version; the world uses tools/build_world.py)

Run both again any time to bring the app up to date. Months that are not finished are
outlined in the table, left out of the medians, and left out of the harmonization ratios.

### 8. Globe extras
- **Labels and borders:** a transparent Esri layer of country borders and place names.
- **Search:** type a country (e.g. `Brazil`, `USA`, `Russia`) to select it and open its results, a place (looked up with OpenStreetMap's Nominatim) or `lat, lon`. The results panel is titled with the country's name, or the rectangle's latitudes and longitudes; the exact coordinates sit under "Edit coordinates".
- **Auto-rotate:** the globe turns slowly when zoomed out, untouched for 6 seconds and
  nothing is selected.
- **Selection readout:** area, size and corner coordinates, live while you drag.

### 9. The fire map (month slider and year box)
- The build writes heat files (`data/heat0/`, `data/heat1/`): for every month, the hotspot
  count of each small map cell on both scales.
- In the app, the bar at the bottom left has a slider with the 12 months and a box where
  you type the year. Changing either loads that year's file and redraws the map.
- The colours come from MapLibre's "heatmap" layer: where many hotspots sit close together
  the colour climbs from dark red to red to orange to yellow. The strength uses a log scale,
  so one huge fire does not hide the smaller ones.
- **Play** animates the whole world from November 2000 to the latest month (2x speed) with a
  fixed colour scale, so months can be compared. Pause, or touch the slider, to stop.
- The calendar table uses the same fire colours: darker = fewer hotspots, lighter = more.
- **Starting month:** the map opens on January 2025.

### 10. The whole world (`tools/build_world.py`, `tools/fetch_nrt_world.py`)
- Source: NASA FIRMS country archives for every country, MODIS 2000-2025 and VIIRS
  2012-2025 (8,337 CSV files, 29 GB, 392.6 million hotspots), plus 2026 from the API.
- `build_world.py` reads the files four at a time and stores them in 10-degree blocks,
  1-degree tiles, and, where fires are dense, up to 16 x 16 cells per tile. Monthly totals
  are kept at every level, so any selection is answered in milliseconds and only the
  pieces cut by its edge are read point by point. Checked: identical to counting every
  hotspot one by one.
- Every hotspot gets its weight on the two scales (section 4). Worldwide, VIIRS sees 3.9 to
  5.1 times more hotspots than MODIS (Terra and Aqua together), depending on the month.
- For hotspots read one by one along a selection's edge, the app looks their weights up in
  `data/factors/`: one small file per 1-degree square, by 0.25 degree cell and month.
- 2026: for the whole world, FIRMS returns one day per request and charges 36 of the
  5,000 credits allowed per 10 minutes, so `fetch_nrt_world.py` paces itself (about an
  hour). It keeps only points inside a country (Natural Earth outline) to match the
  archives; checked against 10 July 2025, it agrees with the archive within 0.3%.
- VIIRS outages are filled with MODIS (see section 12).

### 13. Smaller downloads (`tools/deploy.sh`, `fetchWhole` in `app.js`)
- The files the browser reads in one piece (`coarse.bin`, `countries.bin` and the world fire-map
  months in `heat0/`) are also published gzip-compressed (`name.gz`), about 3x smaller: the
  start-up file goes from 1.6 MB to 0.46 MB, a country's totals from 0.94 MB to 0.29 MB, a
  fire-map month from about 0.17 MB to 0.11 MB (Play: about 54 MB down to 34 MB).
- The browser unpacks them itself (`DecompressionStream`). If a `.gz` copy is missing (the app
  run locally) or the browser is too old, it reads the plain file instead.
- The compressed copies are made by `tools/deploy.sh` in the staged site only; the data folder
  is unchanged. Files read by byte ranges (`tiles/`, `heat1/`) stay uncompressed.
- Cloudflare's free plan allows 20,000 files per site, and `data/factors/` alone has about
  16,700 (one per 1-degree square). So `tools/deploy.sh` bundles them, in the staged site
  only, into one file per 10-degree block (`data/factorpacks/`, 413 files: a small table of
  contents, then the squares' files one after the other). `tools/worker.js` answers the app's
  usual request for `data/factors/<square>.bin` with the right piece of the bundle. The app
  and the data folder are unchanged; the site holds about 19,000 files. Checked: 2,000 squares
  served this way are byte-for-byte identical to the original files.

### 12. Filling the VIIRS outage days (`tools/build_world.py`, `find_gaps`)
Some days the VIIRS satellite sends little or no data. The build finds 87 such days
between 2012 and 2026, for example 10-16 July and 24-29 July 2024, and in 2026: 10-12 March,
28-30 April, 1-2 June, 10-16 July, 3-4 and 18 August, 12-13 October, and 3-14 November
(NASA has published no Suomi NPP data after 2 November 2026; rerun the download when it
does, then rebuild). Any day with no VIIRS at all while MODIS saw fires is also an outage day. Counting VIIRS alone would make
those months look calmer than they were. MODIS kept flying, so we use it to fill the hole.
1. **Find the bad days, worldwide.** For every day we divide the VIIRS count by the MODIS
   count (normally about 4 to 5). A day whose ratio falls below half of the median of the
   15 days around it is an outage day.
2. **Find where, for partial outages.** On an outage day, each 10-degree block is checked:
   if its VIIRS count is less than half of what its MODIS count predicts, that block is
   marked as missing VIIRS for that day. On a full outage every block is marked; on a
   partial one (a few lost orbits) only the blocks under those orbits.
3. **Fill.** For those block-days the VIIRS-scale count uses that day's MODIS hotspots with
   their VIIRS-scale weights, exactly as for the years before VIIRS. Original counts are not
   changed.
- Checked: on full-outage days the filled totals match the expected worldwide VIIRS count
  within about 5%. In 2026 the fill adds about 820,000 VIIRS-equivalent hotspots (5%).
  Over the whole record, 11,196 block-days are filled. Example, central Africa: July 2026
  goes up by 20% (VIIRS missing about 7 of 31 days); months without outages do not change.
- The app's monthly table CSV marks those months as "VIIRS + MODIS scaled on VIIRS outage
  days", and the source line under the panel lists the outage days.

### 11. The charts in the panel (and what each answers)
| Chart | Question it answers |
|---|---|
| Calendar table (red → yellow) | When and where has burning happened, month by month? |
| Unusual years | How far above or below the multi-year average was each year? |
| Monthly record | Every month in one line: biggest fire months, long-term change |
| Fire season + critical period | Which months see most fires? The shaded critical period is the shortest run of consecutive months holding at least 80% of a typical year's hotspots (it may run over New Year). |

## Current limits
- Data: the whole world, 2000 to 14 November 2026 (411 million hotspots).
- Both conversions are statistical models, not physical ones, and are weak on small areas (see section 4).
- VIIRS outage days are filled with converted MODIS (section 12): a good estimate, but
  an estimate.
- A country's counts follow Natural Earth's 1:50m border, which differs slightly from
  NASA's own country files (0.06% for Argentina).

## Run it

    python3 tools/serve.py

then open http://localhost:8765 (see README.md for updating the data and publishing).
