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
   the hotspots inside your rectangle per month, and shows a calendar, an anomaly view, two
   charts and download buttons.

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

### 3. Preparing the data (`tools/build_tiles.py`)
Run once, in Python, with no extra packages:

    python3 -I tools/build_tiles.py data/raw/argentina data Argentina

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

### 5. The panel (`app.js` sections 5-6)
- **Calendar:** years as rows, months as columns. Colour is a single blue ramp on a log
  scale (dark = few, light = many), readable with colour-blindness.
- **Anomaly view:** each month compared with the median of the same month across the
  chosen years. Blue = below normal, grey = normal, red = above normal.
- **Headline figures:** total, most active year, peak month of the season, latest month
  against its median.
- **Fire season chart:** median and the middle half of years (25th to 75th percentile),
  with the latest year on top.
- **Hotspots per year** bar chart.
- Year range can be narrowed with the From / To menus.

### 6. Downloads (`app.js` section 7)
- Monthly table (CSV): raw MODIS, raw VIIRS and harmonized value for every month.
- Hotspots in the search (CSV): every detection, with a `harmonized_weight` column
  (limited to 500,000 rows).
- Calendar and charts (PNG).

### 7. The current year (`tools/fetch_nrt.py`)
NASA's yearly archive files stop at the end of last year. For 2026 the script asks the
FIRMS API (which needs a free key, stored in `.firms_key`, never shared) for every 5-day
window since 1 January, inside a rectangle around Argentina, and keeps only the points
inside Argentina's border (outline from Natural Earth, public domain). It takes
science-quality data as far as it exists and near-real-time data for the latest weeks.

    python3 -I tools/fetch_nrt.py data/raw/argentina 2026
    python3 -I tools/build_tiles.py data/raw/argentina data Argentina

Run both again any time to bring the app up to date. Months that are not finished are
outlined in the table, left out of the medians, and left out of the harmonization ratios.

### 8. Globe extras
- **Labels and borders:** a transparent Esri layer of country borders and place names.
- **Search:** type a place (looked up with OpenStreetMap's Nominatim) or `lat, lon`.
- **Auto-rotate:** the globe turns slowly when zoomed out, untouched for 6 seconds and
  nothing is selected.
- **Selection readout:** area, size and corner coordinates, live while you drag.

### 9. The fire map (month slider and year box)
- `build_tiles.py` also writes `data/heat/<year>.bin`: for every month, the harmonized
  hotspot count in each 0.05 degree cell (about 5 km). One small file per year, 7 MB in all.
- In the app, the bar at the bottom left has a slider with the 12 months and a box where
  you type the year. Changing either loads that year's file and redraws the map.
- The glow is MapLibre's "heatmap" layer: each cell adds a soft red spot, and where many
  hotspots sit close together the colour climbs from dark red to bright red to pale pink.
  The strength uses a log scale, so one huge fire does not hide the smaller ones.
- The satellite picture is dimmed while the fire map is on so the reds stand out.
- The calendar table uses the same idea in red: darker = fewer hotspots, lighter = more.

## Current limits
- Data loaded: **Argentina only**, to mid-November 2026. A selection that spills into a
  neighbouring country only counts the Argentine part.
- 1-degree tiles are fine for one country; the whole world will need smaller tiles in
  the busiest regions (central Africa, Brazil).

## Run it

    python3 -m http.server 8765 --directory ~/Work/claude/fire-globe

then open http://localhost:8765
