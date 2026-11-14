# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The NASA Space Apps Challenge 2026 jury. They open the public link, usually once and briefly,
to judge an entry to the challenge "Harmonization of MODIS and VIIRS Hot Spots". They need to
understand within a few minutes what the app does, see that it works on real NASA data, and
see that the harmonization is sound. No other audience is a design priority.

## Product Purpose

Fire Globe turns 25 years of NASA FIRMS fire hotspots into one comparable record. A visitor
spins a satellite globe, selects an area (a rectangle or a whole country) and a date range,
and gets a month-by-month burning-activity calendar from November 2000 to today, with
anomalies, charts and downloads. Success means the jury sees the challenge solved, end to end,
in a working product.

## Positioning

The harmonized record from 2000 to today. MODIS (since 2000) and VIIRS (since 2012) are merged
into one series in VIIRS-equivalent units, using per-tile, per-month VIIRS/MODIS ratios, so
years before and after 2012 can be compared fairly. Days when VIIRS was down are filled with
converted MODIS. The Raw / Harmonized switch shows the fake jump in 2012 disappearing.

## Operating Context

- Judged online through the public link https://fire-globe.fire-globe.workers.dev, alongside
  a short presentation (slides or video) prepared separately by the team.
- The team code lives in GitHub repo louisdenaiffe/modis-viirs-harmonization, branch
  lucille-fire-globe-v2, folder webapp/.
- A teammate is producing a separate harmonization in Aqua-equivalent units; it will be added
  to the app later.

## Capabilities and Constraints

- Static site, no server logic: plain HTML/CSS/JS (`index.html`, `app.js`) with MapLibre GL
  (globe), Esri World Imagery, Natural Earth borders. Hosted on Cloudflare Workers static
  assets; the browser reads binary data files with range requests.
- Data: NASA FIRMS MODIS C6.1 (Terra, Aqua) and VIIRS S-NPP 375 m, 2000 to 14 Nov 2026,
  about 411 million hotspots, converted by `tools/build_world.py`.
- Features: rectangle selection (Shift+drag, or Select then drag), country selection
  (Shift+click, or Select then tap), month-level date range, calendar table, Counts/Anomaly
  and Raw/Harmonized switches, charts (Unusual years, Monthly record, Fire season with
  critical period), world fire map with month slider, year box and Play, downloads (monthly
  table CSV, hotspots-in-search CSV, PNG).
- Removed on purpose; do not reintroduce unless asked: per-year naive-vs-harmonized chart,
  year-to-date chart, Excel download, Play speed button, "How does the latest fire activity
  compare?" box.
- Terminology: "hotspots", "VIIRS-equivalent hotspots", "Raw", "Harmonized", "anomaly",
  "fire season", "critical period".
- Open: how the teammate's Aqua-equivalent data will be shown alongside the current one.

## Brand Commitments

- Name: Fire Globe.
- Language: English only, including CSV formats (comma separator, dot decimals).
- Standing user preferences: fire data in red / orange / yellow; Raw view uses olive green for
  MODIS and slate blue for VIIRS; bright satellite imagery; no glow around the globe; a glassy
  results panel; two decorative satellites in orbit (non-interactive).
- Credits shown: NASA FIRMS, Esri, Natural Earth, OpenStreetMap Nominatim, MapLibre, and a
  note that an AI coding assistant (Claude) helped build it.

## Evidence on Hand

- Live, working product on real data (link above).
- Validation results in `HOW_IT_WORKS.md`: country counts identical to point-by-point
  counting; Argentina within 0.06% of NASA's own country file; 2026 API data within 0.3% of
  the archive; outage fill consistent with stored totals.
- No user testimonials, usage figures or press exist; none may be invented.

## Product Principles

1. The harmonization is the story: every view should make it easy to see that 2000-2011 and
   2012-today are comparable, and how.
2. Honest data: show limits (estimates, incomplete months, filled outages) plainly; never
   imply more precision than the method has.
3. A judge must get it in minutes: the first screen and first click should lead to a result
   without instructions.
4. Real NASA data only; no placeholder or invented figures.
