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
into one series, so years before and after 2012 can be compared fairly. A VIIRS / MODIS switch
shows the whole record on either scale: VIIRS-equivalent hotspots (375 m pixels; before 2012
MODIS is converted by the team's MODIS-to-VIIRS model) or MODIS Aqua-equivalent hotspots (1 km
pixels; before July 2002 and from 2022 the team's VIIRS-to-MODIS model converts Terra and
VIIRS). Days when VIIRS was down are filled with converted MODIS.

## Operating Context

- Judged online through the public link https://fire-globe.fire-globe.workers.dev, alongside
  a short presentation (slides or video) prepared separately by the team.
- The team code lives in GitHub repo louisdenaiffe/modis-viirs-harmonization, branch
  lucille-fire-globe-v2, folder webapp/.
- The two conversion models come from teammates as per-cell monthly tables (HOW_IT_WORKS.md
  section 4); the data build turns them into a weight per hotspot on each scale.

## Capabilities and Constraints

- Static site, no server logic: plain HTML/CSS/JS (`index.html`, `app.js`) with MapLibre GL
  (globe), Esri World Imagery, Natural Earth borders. Hosted on Cloudflare Workers static
  assets; the browser reads binary data files with range requests.
- Data: NASA FIRMS MODIS C6.1 (Terra, Aqua) and VIIRS S-NPP 375 m, 2000 to 14 Nov 2026,
  about 411 million hotspots, converted by `tools/build_world.py`.
- Features: rectangle selection (Shift+drag, or Select then drag), country selection
  (Shift+click, or Select then tap), month-level date range, calendar table, Counts/Anomaly
  and VIIRS/MODIS units switches (the units switch also sits by the fire map), charts (Unusual years, Monthly record, Fire season with
  critical period), world fire map with month slider, year box and Play, downloads (monthly
  table CSV, hotspots-in-search CSV, PNG).
- Removed on purpose; do not reintroduce unless asked: per-year naive-vs-harmonized chart,
  year-to-date chart, Excel download, Play speed button, "How does the latest fire activity
  compare?" box, the Raw / Harmonized switch and its green/blue sensor colours (replaced by
  the VIIRS / MODIS units switch; tables stay red / orange / yellow).
- Terminology: "hotspots", "VIIRS-equivalent hotspots", "MODIS Aqua-equivalent hotspots", "VIIRS
  units (375 m)", "MODIS units (1 km)", "anomaly",
  "fire season", "critical period".
- Done: the teammates' VIIRS-to-MODIS and MODIS-to-VIIRS models replaced the provisional
  MODIS-unit filler and the per-tile ratios.

## Brand Commitments

- Name: Fire Globe.
- Language: English only, including CSV formats (comma separator, dot decimals).
- Standing user preferences: fire data in red / orange / yellow everywhere (no sensor
  colours); bright satellite imagery; no glow around the globe; glassy floating boxes and
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
