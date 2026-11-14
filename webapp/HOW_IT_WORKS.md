# Fire Globe: what it does and how it was built

A web app for the NASA Space Apps 2026 challenge "Harmonization of MODIS and VIIRS Hot Spots".
You spin a globe, draw a rectangle, and get a burning-activity calendar for that area from
2000 to today, with MODIS and VIIRS merged into one comparable record.

## The one-minute explanation

1. **Data.** NASA FIRMS publishes every fire hotspot its satellites detect. We use two
   sensors: MODIS (on the Terra and Aqua satellites, since November 2000) and VIIRS (on the
   Suomi NPP satellite, since January 2012).
2. **Problem.** VIIRS has sharper eyes (375 m pixels against 1 km), so it reports roughly
   3 to 4 times more hotspots than MODIS for the same fires. Putting the two records end to
   end shows a fake jump in 2012.
3. **Harmonization.** For the years when both sensors flew together, we measure how many
   VIIRS hotspots there are per MODIS hotspot, place by place and month by month. We multiply
   the old MODIS counts by that ratio. Every year is then expressed in "VIIRS-equivalent
   hotspots".
4. **App.** The page reads the prepared data directly in the browser (no server), adds up
   the hotspots inside your rectangle (or country) per month, and shows a calendar, an anomaly
   view, three charts, a month-by-month fire map and download buttons.

## Step by step

### 1. The globe (`index.html`, `app.js` sections 1-2)
- **MapLibre GL JS** (open source) draws the 3D globe. A copy is stored in `vendor/`.
- **Esri World Imagery** provides the satellite pictures, down to about 0.6 m per pixel.
- The stars are random dots drawn on a canvas behind the globe.
- Zoom speed is set to about 3 times MapLibre's default.

### 2. Selecting an area (`app.js` section 3)
- Hold **Shift and drag**, or press **Select** and drag (one finger on a touch screen).
- The rectangle is defined by two latitudes and two longitudes, and its edges are drawn
  with many intermediate points, so it lies on the curved surface.
- Minimum size is 375 m x 375 m (one VIIRS pixel). There is no maximum.
- Orange corner dots resize it; exact coordinates can be typed in the panel.

### 2b. Selecting a whole country (Shift + click)
- Hold **Shift and click** (without dragging) on a country: its border is outlined and
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

### 4. The harmonization (computed in `build_tiles.py`, applied in `app.js` section 4)
- Reference sensor: **VIIRS**.
- Overlap period: February 2012 to the latest month both sensors have.
- For each square and each month of the year (12 values per square):

      ratio = (VIIRS hotspots + K x national ratio) / (MODIS hotspots + K),  K = 20

  The K term is "shrinkage": where a square has few fires, its ratio leans toward the
  national one, so a handful of detections cannot produce an absurd factor.
- A second ratio, VIIRS / Terra only, is used for November 2000 to June 2002, when Aqua
  had not been launched and MODIS saw only the morning overpass.
- Final series: before February 2012 = MODIS count x ratio; from February 2012 = VIIRS count.
- Measured for Argentina: the VIIRS/MODIS ratio is between 3.1 (August) and 4.0 (March).
- The **Raw / Harmonized** switch in the panel shows the effect.

Limits to be honest about: this is a statistical scaling of counts, not a physical model.
It assumes the VIIRS/MODIS relationship of 2012-2025 also held in 2000-2011, and it does
not correct for MODIS sensor ageing or for individual satellite outages.

### 5. The panel (`app.js`)
- **Calendar:** years as rows, months as columns. In the **Harmonized** view the colour runs
  from dark red (few hotspots) through orange to yellow (many), on a log scale.
- **Raw view:** the colour tells you which satellite the number comes from, the shade how
  many hotspots. Purple shades = MODIS (before February 2012), teal shades = VIIRS (from
  February 2012), darker = fewer, lighter = more, on the same scale for both.
- **Anomaly view:** each month compared with the median of the same month across the
  chosen years. Blue = below normal, grey = normal, red = above normal.
- **Headline figures:** total, most active year, peak month of the season, latest month
  against its median.
- **Charts:** unusual years, monthly record, fire season with its critical period (table in
  section 11).
- The date range is chosen month by month (From / To), or with **Last 12 months** / **All**.

### 6. Downloads (`app.js`)
- **Monthly table (CSV):** raw MODIS, raw VIIRS and harmonized value for every month.
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
- **Search:** type a place (looked up with OpenStreetMap's Nominatim) or `lat, lon`.
- **Auto-rotate:** the globe turns slowly when zoomed out, untouched for 6 seconds and
  nothing is selected.
- **Selection readout:** area, size and corner coordinates, live while you drag.

### 9. The fire map (month slider and year box)
- The build writes yearly heat files (`data/heat0/`, `data/heat1/`): for every month, the
  harmonized hotspot count in each small map cell.
- In the app, the bar at the bottom left has a slider with the 12 months and a box where
  you type the year. Changing either loads that year's file and redraws the map.
- The colours come from MapLibre's "heatmap" layer: where many hotspots sit close together
  the colour climbs from dark red to red to orange to yellow. The strength uses a log scale,
  so one huge fire does not hide the smaller ones.
- **Play** animates the whole world from November 2000 to the latest month (2x speed) with a
  fixed colour scale, so months can be compared. Pause, or touch the slider, to stop.
- The calendar table uses the same fire colours: darker = fewer hotspots, lighter = more.

### 10. The whole world (`tools/build_world.py`, `tools/fetch_nrt_world.py`)
- Source: NASA FIRMS country archives for every country, MODIS 2000-2025 and VIIRS
  2012-2025 (8,337 CSV files, 29 GB, 392.6 million hotspots), plus 2026 from the API.
- `build_world.py` reads the files four at a time and stores them in 10-degree blocks,
  1-degree tiles, and, where fires are dense, up to 16 x 16 cells per tile. Monthly totals
  are kept at every level, so any selection is answered in milliseconds and only the
  pieces cut by its edge are read point by point. Checked: identical to counting every
  hotspot one by one.
- Harmonization ratios are computed per tile and month of the year; sparse tiles lean on
  their 10-degree block, and blocks on the global ratio (VIIRS sees 3.9 to 5.1 times more
  hotspots than MODIS worldwide, depending on the month).
- 2026: for the whole world, FIRMS returns one day per request and charges 36 of the
  5,000 credits allowed per 10 minutes, so `fetch_nrt_world.py` paces itself (about an
  hour). It keeps only points inside a country (Natural Earth outline) to match the
  archives; checked against 10 July 2025, it agrees with the archive within 0.3%.
- Known gap: the VIIRS satellite has outage days in 2026 (for example 10-12 March, half
  of 10 July). Those months are slightly undercounted.

### 11. The charts in the panel (and what each answers)
| Chart | Question it answers |
|---|---|
| Calendar table (red → yellow) | When and where has burning happened, month by month? |
| Unusual years | How far above or below the multi-year average was each year? |
| Monthly record | Every month in one line: biggest fire months, long-term change |
| Fire season + critical period | Which months see most fires? The shaded critical period is the shortest run of consecutive months holding at least 80% of a typical year's hotspots (it may run over New Year). |

## Current limits
- Data: the whole world, 2000 to 14 November 2026 (411 million hotspots).
- The harmonization is a statistical scaling of counts, not a physical model (see section 4).
- The VIIRS satellite has outage days in 2026 (for example 10-12 March, half of 10 July).
  Those months are slightly undercounted.
- A country's counts follow Natural Earth's 1:50m border, which differs slightly from
  NASA's own country files (0.06% for Argentina).

## Run it

    python3 tools/serve.py

then open http://localhost:8765 (see README.md for updating the data and publishing).
