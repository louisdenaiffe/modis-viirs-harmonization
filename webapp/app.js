'use strict';
/* Fire Globe: globe + area selection + harmonized burning-activity calendar.
   Sections: 1 starfield, 2 globe, 3 selection, 4 data, 5 panel, 6 charts, 7 downloads. */

const EARTH_R = 6371008.8;              // mean Earth radius, metres
const MIN_SIDE_M = 375;                 // one VIIRS pixel: smallest allowed selection side
const DEG = Math.PI / 180;
// Play / Pause icons for the fire-map button (drawn, so they match across systems).
// The triangle sits a little right of centre, so it looks centred in the round button.
const ICON_PLAY = '<span class="ico"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><path d="M4 1.8v11.4c0 .6.6.9 1.1.6l8.6-5.7c.4-.3.4-.9 0-1.2L5.1 1.2C4.6.9 4 1.2 4 1.8z" fill="currentColor"/></svg></span>';
const ICON_PAUSE = '<span class="ico"><svg width="15" height="15" viewBox="0 0 15 15" aria-hidden="true"><rect x="3" y="2" width="3.4" height="11" rx="1" fill="currentColor"/><rect x="8.6" y="2" width="3.4" height="11" rx="1" fill="currentColor"/></svg></span>';
const M_PER_DEG_LAT = EARTH_R * DEG;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];
const $ = id => document.getElementById(id);

/* ================= 1. Starfield ================= */
(function stars() {
  const cv = $('stars'), ctx = cv.getContext('2d');
  const rng = seed => () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
  function draw() {
    const dpr = window.devicePixelRatio || 1;
    const w = cv.width = innerWidth * dpr, h = cv.height = innerHeight * dpr;
    const r = rng(42);
    ctx.clearRect(0, 0, w, h);
    const n = Math.round((innerWidth * innerHeight) / 900);
    for (let i = 0; i < n; i++) {
      const x = r() * w, y = r() * h, m = r();
      const size = (m < 0.92 ? 0.4 + r() * 0.7 : 1.1 + r() * 1.2) * dpr;
      const tint = r();
      const color = tint < 0.15 ? '190,205,255' : tint < 0.3 ? '255,225,195' : '255,255,255';
      ctx.fillStyle = `rgba(${color},${0.35 + r() * 0.65})`;
      ctx.beginPath(); ctx.arc(x, y, size, 0, 6.2832); ctx.fill();
      if (m > 0.985) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, size * 7);
        g.addColorStop(0, `rgba(${color},0.35)`); g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, size * 7, 0, 6.2832); ctx.fill();
      }
    }
  }
  draw(); addEventListener('resize', draw);
})();

/* ================= 2. Globe ================= */
const map = new maplibregl.Map({
  container: 'map',
  center: [-62, -36],
  zoom: 2.2,
  minZoom: 0.6,
  maxZoom: 20,
  boxZoom: false,                         // Shift+drag is ours
  attributionControl: { compact: true },
  style: {
    version: 8,
    projection: { type: 'globe' },
    sources: {
      imagery: {
        type: 'raster', tileSize: 256, maxzoom: 18,
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        attribution: 'Hotspots: NASA FIRMS (MODIS C6.1, VIIRS S-NPP) · Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community · ' +
          'Borders: Natural Earth · Search: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors (Nominatim) · ' +
          'Built by the team with help from Claude, an AI coding assistant'
      },
      labels: {
        type: 'raster', tileSize: 256, maxzoom: 13,
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}']
      },
      aoi: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      heat: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } }
    },
    layers: [
      { id: 'imagery', type: 'raster', source: 'imagery' },
      // Fire map: a red glow whose strength follows the number of hotspots in each ~5 km cell.
      { id: 'heat', type: 'heatmap', source: 'heat', paint: {
        'heatmap-weight': ['interpolate', ['linear'], ['ln', ['+', 1, ['get', 'w']]], 0, 0, 7, 1],
        'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 0.9, 2, 1.2, 3, 1.5, 4.5, 1.9, 6, 2.2, 10, 2.6],
        'heatmap-radius': ['interpolate', ['exponential', 2], ['zoom'], 1, 2, 4, 4, 7, 12, 10, 90],
        'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
          0, 'rgba(110,12,6,0)', 0.04, 'rgba(138,22,9,0.65)', 0.18, '#c4240d', 0.35, '#e8471a', 0.52, '#f37a22', 0.68, '#f9a72f', 0.84, '#fdd23f', 1, '#fff07a'],
        'heatmap-opacity': 0.92
      } },
      { id: 'labels', type: 'raster', source: 'labels' },
      // Outline only, no tinted fill: while zooming, the globe can briefly draw a shape's coarse and
      // detailed copies on top of each other, which made part of a big country (Russia) look whiter.
      { id: 'aoi-line', type: 'line', source: 'aoi', filter: ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]], paint: { 'line-color': '#ffffff', 'line-width': 2.5 } }
    ]
  }
});
// Faster zoom: 3x the default speed for a mouse wheel, about 3x for a trackpad.
map.scrollZoom.setWheelZoomRate(1 / 150);
map.scrollZoom.setZoomRate(1 / 35);
window.fireGlobe = { map, selection: null };

/* ================= 3. Selection ================= */
const wrapLng = l => ((l + 540) % 360) - 180;

// Rectangle bounded by two parallels and two meridians, densified so its edges
// follow the curvature of the globe instead of cutting straight across it.
function rectPolygon(b) {
  const ring = [];
  const nLng = Math.max(2, Math.ceil((b.east - b.west) / 0.5));
  const nLat = Math.max(2, Math.ceil((b.north - b.south) / 0.5));
  for (let i = 0; i <= nLng; i++) ring.push([b.west + (b.east - b.west) * i / nLng, b.south]);
  for (let i = 1; i <= nLat; i++) ring.push([b.east, b.south + (b.north - b.south) * i / nLat]);
  for (let i = 1; i <= nLng; i++) ring.push([b.east - (b.east - b.west) * i / nLng, b.north]);
  for (let i = 1; i <= nLat; i++) ring.push([b.west, b.north - (b.north - b.south) * i / nLat]);
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } };
}
// Box between two points, going the short way round in longitude (east may exceed 180).
function boxFrom(a, c) {
  const d = wrapLng(c.lng - a.lng);
  return {
    west: Math.min(a.lng, a.lng + d), east: Math.max(a.lng, a.lng + d),
    south: Math.max(-90, Math.min(a.lat, c.lat)), north: Math.min(90, Math.max(a.lat, c.lat))
  };
}
// Grow a box around its centre so each side is at least one VIIRS pixel (375 m).
function enforceMin(b) {
  const midLat = (b.south + b.north) / 2, midLng = (b.west + b.east) / 2;
  const minLat = MIN_SIDE_M / M_PER_DEG_LAT;
  const minLng = MIN_SIDE_M / (M_PER_DEG_LAT * Math.max(0.01, Math.cos(midLat * DEG)));
  const out = { ...b };
  if (b.north - b.south < minLat) { out.south = midLat - minLat / 2; out.north = midLat + minLat / 2; }
  if (b.east - b.west < minLng) { out.west = midLng - minLng / 2; out.east = midLng + minLng / 2; }
  return out;
}
const areaM2 = b =>
  EARTH_R * EARTH_R * (b.east - b.west) * DEG * (Math.sin(b.north * DEG) - Math.sin(b.south * DEG));

const mapEl = $('map'), selectBtn = $('selectBtn');
let selectMode = false, drag = null, currentBox = null;

function lockPan(lock) {
  for (const h of [map.dragPan, map.touchZoomRotate]) lock ? h.disable() : h.enable();
}
function setSelectMode(on) {
  selectMode = on;
  selectBtn.classList.toggle('active', on);
  mapEl.classList.toggle('selecting', on);
  lockPan(on);
}
// The outline is drawn from its own lines. Drawing it from the filled shape
// would also trace the straight edges where the map cuts shapes into tiles (a line across
// Russia at 90°E when zoomed out) and the seam where a country is split at the 180° meridian.
function aoiFeatures(polys) {
  const lines = [];
  for (const poly of polys) for (const r of poly) {
    let cur = [r[0]];
    for (let i = 1; i < r.length; i++) {
      const a = r[i - 1], b = r[i];
      if (Math.abs(a[0]) === 180 && a[0] === b[0]) {          // along the 180° seam: break the line
        if (cur.length > 1) lines.push(cur);
        cur = [b];
      } else cur.push(b);
    }
    if (cur.length > 1) lines.push(cur);
  }
  return { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: lines } }] };
}
function drawBox(b) {
  map.getSource('aoi').setData(b ? aoiFeatures([rectPolygon(b).geometry.coordinates]) : { type: 'FeatureCollection', features: [] });
  showReadout(b);
}
// Live readout of the rectangle being drawn or selected: size and corner coordinates.
function showReadout(b) {
  const box = $('readout');
  box.hidden = !b;
  if (!b) return;
  const n = (v, d) => v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  const len = m => (m < 1000 ? n(m, 0) + ' m' : n(m / 1000, m < 100000 ? 2 : 0) + ' km');
  const a = areaM2(b), mid = (b.south + b.north) / 2;
  const lat = v => n(Math.abs(v), 4) + '° ' + (v >= 0 ? 'N' : 'S');
  const lng = v => { v = wrapLng(v); return n(Math.abs(v), 4) + '° ' + (v >= 0 ? 'E' : 'W'); };
  box.textContent = '';
  const row = (k, v) => { const d = document.createElement('div'), s = document.createElement('span'); s.textContent = k; d.append(s, v); box.append(d); };
  const head = document.createElement('b');
  head.textContent = a < 1e6 ? n(a, 0) + ' m² (' + n(a / 1e4, 1) + ' ha)' : n(a / 1e6, a < 1e9 ? 2 : 0) + ' km²';
  box.append(head);
  row('Size', len((b.east - b.west) * M_PER_DEG_LAT * Math.cos(mid * DEG)) + ' × ' + len((b.north - b.south) * M_PER_DEG_LAT));
  row('North', lat(b.north)); row('South', lat(b.south)); row('West', lng(b.west)); row('East', lng(b.east));
}

// Four draggable corner dots: SW, SE, NE, NW. Dragging one keeps the opposite corner fixed.
let handleDraft = null, handleFixed = null;
const handles = [0, 1, 2, 3].map(i => {
  const el = document.createElement('div');
  el.className = 'handle';
  el.title = 'Drag to resize the selection';
  const mk = new maplibregl.Marker({ element: el, draggable: true });
  mk.on('dragstart', () => { handleFixed = handles[(i + 2) % 4].getLngLat(); handleDraft = null; });
  mk.on('drag', () => {
    const p = mk.getLngLat(), f = handleFixed;
    handleDraft = boxFrom(f, p);
    drawBox(handleDraft);
    handles[(i + 1) % 4].setLngLat([p.lng, f.lat]);
    handles[(i + 3) % 4].setLngLat([f.lng, p.lat]);
  });
  mk.on('dragend', () => { if (handleDraft) commit(enforceMin(handleDraft)); });
  return mk;
});
function placeHandles(b) {
  if (!b) { handles.forEach(h => h.remove()); return; }
  [[b.west, b.south], [b.east, b.south], [b.east, b.north], [b.west, b.north]]
    .forEach((c, i) => handles[i].setLngLat(c).addTo(map));
}

// Store the selection, redraw it, and tell the panel.
function commit(b) {
  committedAt = performance.now();
  currentBox = b;
  currentCountry = null;
  drawBox(b);
  placeHandles(b);
  window.fireGlobe.selection = b && {
    west: wrapLng(b.west), east: wrapLng(b.east), south: b.south, north: b.north,
    crossesAntimeridian: wrapLng(b.east) < wrapLng(b.west), areaM2: areaM2(b)
  };
  window.dispatchEvent(new CustomEvent('aoi-selected', { detail: window.fireGlobe.selection }));
}

function startDrag(lngLat, point, shift = false) {
  lockPan(true);
  mapEl.classList.add('selecting');
  placeHandles(null);
  drag = { start: lngLat, point, shift, moved: false, box: null };
}
// Put back whatever is currently selected (a rectangle or a country).
function redrawSelection() {
  if (currentCountry) drawCountry(currentCountry);
  else { drawBox(currentBox); placeHandles(currentBox); }
}
function moveDrag(lngLat, point) {
  if (Math.hypot(point.x - drag.point.x, point.y - drag.point.y) > 3) drag.moved = true;
  if (!drag.moved) return;
  drag.box = boxFrom(drag.start, lngLat);
  drawBox(drag.box);
}
function endDrag(cancel) {
  if (!drag) return;
  const d = drag; drag = null;
  if (cancel || !d.moved) {
    // Shift + click, or a tap/click in Select mode (phones have no Shift key), without
    // dragging: select the country under the cursor.
    const country = !cancel && (d.shift || selectMode);
    if (country && selectMode) setSelectMode(false);
    redrawSelection();
    mapEl.classList.toggle('selecting', selectMode);
    if (!selectMode) lockPan(false);
    if (country) selectCountryAt(d.start);
    return;
  }
  setSelectMode(false);
  commit(enforceMin(d.box));
}
map.on('mousedown', e => {
  if (e.originalEvent.button !== 0 || !(selectMode || e.originalEvent.shiftKey)) return;
  e.preventDefault();
  startDrag(e.lngLat, e.point, e.originalEvent.shiftKey && !selectMode);
});
map.on('mousemove', e => { if (drag) moveDrag(e.lngLat, e.point); });
addEventListener('mouseup', () => endDrag(false));
// Touch screens: press Select, then drag one finger.
map.on('touchstart', e => {
  if (!selectMode || e.points.length !== 1) return;
  e.preventDefault();
  startDrag(e.lngLat, e.point);
});
map.on('touchmove', e => { if (drag) { e.preventDefault(); moveDrag(e.lngLat, e.point); } });
map.on('touchend', () => endDrag(false));
map.on('touchcancel', () => endDrag(true));
addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (drag) endDrag(true); else setSelectMode(false);
});
// A plain click on the map outside the rectangle removes the selection.
let committedAt = 0;
map.on('click', e => {
  const b = currentBox;
  if (selectMode || e.originalEvent.shiftKey || performance.now() - committedAt < 400) return;
  if (currentCountry) {
    if (!ringsContain(currentCountry.p, wrapLng(e.lngLat.lng), e.lngLat.lat)) commit(null);
    return;
  }
  if (!b) return;
  const dLng = wrapLng(e.lngLat.lng - b.west), inside = e.lngLat.lat >= b.south && e.lngLat.lat <= b.north &&
    ((dLng + 360) % 360) <= b.east - b.west;
  if (!inside) commit(null);
});
selectBtn.onclick = () => setSelectMode(!selectMode);
$('clearBtn').onclick = () => commit(null);

/* ----- Country selection: Shift + click ----- */
// Outlines from Natural Earth 1:50m (public domain): [{ n: name, b: [w, s, e, n], p: polygons }].
let currentCountry = null, countriesP = null;
const loadCountries = () => countriesP || (countriesP = fetch('geo/countries.json').then(r => r.json()).then(list => { list.forEach((c, i) => { c.i = i; }); return list; }));
// Even-odd rule over every ring of every polygon (holes and islands handled alike).
function ringsContain(polys, x, y) {
  let c = false;
  for (const poly of polys) for (const r of poly) for (let i = 0; i < r.length - 1; i++) {
    const x1 = r[i][0], y1 = r[i][1], x2 = r[i + 1][0], y2 = r[i + 1][1];
    if ((y1 > y) !== (y2 > y) && x < x1 + (y - y1) * (x2 - x1) / (y2 - y1)) c = !c;
  }
  return c;
}
// Area on the sphere (same formula as Turf.js): outer rings minus holes.
function countryArea(c) {
  const ring = r => {
    let a = 0;
    for (let i = 0; i < r.length - 1; i++)
      a += (r[i + 1][0] - r[i][0]) * DEG * (2 + Math.sin(r[i][1] * DEG) + Math.sin(r[i + 1][1] * DEG));
    return Math.abs(a * EARTH_R * EARTH_R / 2);
  };
  return c.p.reduce((sum, poly) => sum + ring(poly[0]) - poly.slice(1).reduce((h, r) => h + ring(r), 0), 0);
}
function drawCountry(c) {
  map.getSource('aoi').setData(aoiFeatures(c.p));
  // No floating name box: the results panel already carries the country's name and size.
  $('readout').hidden = true;
}
async function countryAt(ll) {
  const x = wrapLng(ll.lng), y = ll.lat, list = await loadCountries();
  return list.find(k => x >= k.b[0] && x <= k.b[2] && y >= k.b[1] && y <= k.b[3] && ringsContain(k.p, x, y));
}
async function selectCountryAt(ll) {
  const c = await countryAt(ll);
  if (c) selectCountry(c);                          // clicked on the ocean: keep the current selection
}
function selectCountry(c) {
  if (c.area === undefined) c.area = countryArea(c);
  committedAt = performance.now();
  currentBox = null;
  currentCountry = c;
  placeHandles(null);
  drawCountry(c);
  window.fireGlobe.selection = { west: c.b[0], south: c.b[1], east: c.b[2], north: c.b[3],
    crossesAntimeridian: false, areaM2: c.area, country: c.n, poly: c };
  window.dispatchEvent(new CustomEvent('aoi-selected', { detail: window.fireGlobe.selection }));
}

/* ----- Two decorative satellites circling the globe ----- */
// Drawn on a transparent canvas above the map (no clicks). Each flies a tilted circle a little
// above the surface; on the far side of the globe it is hidden behind it. Zoomed in close to the
// ground they fade away.
(function satellites() {
  const cv = $('sats'), ctx = cv.getContext('2d');
  // Two vector drawings of an Earth-observing satellite, seen at a slight angle and flying
  // toward +x: a shaded silver cylinder (dark sensor dish in front, copper engine nozzle at
  // the back) with two long blue solar wings on a mast across it. The second one is shorter,
  // wrapped in gold thermal foil in the middle, with longer wings.
  const DEFS = `<defs>
    <linearGradient id="cyl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#59626c"/><stop offset=".22" stop-color="#d9dee4"/><stop offset=".38" stop-color="#ffffff"/><stop offset=".62" stop-color="#c3cad2"/><stop offset=".85" stop-color="#7d8792"/><stop offset="1" stop-color="#4b535c"/></linearGradient>
    <linearGradient id="band" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3d444c"/><stop offset=".35" stop-color="#a9b1ba"/><stop offset=".6" stop-color="#7c858f"/><stop offset="1" stop-color="#2f353b"/></linearGradient>
    <linearGradient id="foil" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7a5414"/><stop offset=".25" stop-color="#e7bf5c"/><stop offset=".4" stop-color="#fff0b8"/><stop offset=".65" stop-color="#c8952e"/><stop offset="1" stop-color="#5e3f0c"/></linearGradient>
    <linearGradient id="panel" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#2a5aa6"/><stop offset=".45" stop-color="#6ea6e6"/><stop offset=".55" stop-color="#8dbdf2"/><stop offset="1" stop-color="#2d5ea9"/></linearGradient>
    <radialGradient id="dishIn" cx=".45" cy=".4" r=".7"><stop offset="0" stop-color="#3a414a"/><stop offset=".7" stop-color="#14171b"/><stop offset="1" stop-color="#050607"/></radialGradient>
    <radialGradient id="copper" cx=".4" cy=".4" r=".75"><stop offset="0" stop-color="#ffd2a3"/><stop offset=".45" stop-color="#d07a3c"/><stop offset="1" stop-color="#5a2a10"/></radialGradient>
    <pattern id="cells" width="5" height="5" patternUnits="userSpaceOnUse"><path d="M5 0H0V5" fill="none" stroke="#d4e7ff" stroke-opacity=".45" stroke-width=".45"/></pattern>
  </defs>`;
  const svgSat = body => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-100 -100 200 200" width="600" height="600">${DEFS}${body}</svg>`;
  // One solar wing: a slightly slanted panel from the mast outward, cut into segments.
  function wing(sign, len, segs) {
    const y0 = sign * 17, y1 = sign * (17 + len), dx = sign * len * 0.16;
    const pts = `${-9},${y0} ${9},${y0} ${9 + dx},${y1} ${-9 + dx},${y1}`;
    let out = `<polygon points="${pts}" fill="#8e98a3"/>` +
      `<polygon points="${pts}" fill="url(#panel)" transform="translate(0 ${sign * 0.8}) scale(1 1)"/>` +
      `<polygon points="${pts}" fill="url(#cells)"/>`;
    for (let k = 1; k < segs; k++) {
      const t = k / segs, y = y0 + (y1 - y0) * t, x = dx * t;
      out += `<line x1="${-9 + x}" y1="${y}" x2="${9 + x}" y2="${y}" stroke="#c9d3de" stroke-width="1.1"/>`;
    }
    return out + `<polygon points="${pts}" fill="none" stroke="#c9d3de" stroke-width="1"/>` +
      `<line x1="0" y1="${y0}" x2="${dx * 0.5}" y2="${(y0 + y1) / 2}" stroke="#ffffff" stroke-opacity=".25" stroke-width="2"/>`;
  }
  function satellite(len, foil, wingLen, segs) {
    const x0 = -len / 2, x1 = len / 2;
    return svgSat(`
      <rect x="-2.2" y="-19" width="4.4" height="38" fill="url(#band)"/>
      ${wing(-1, wingLen, segs)}${wing(1, wingLen, segs)}
      <rect x="${x0 - 12}" y="-9" width="14" height="18" rx="3" fill="url(#cyl)"/>
      <ellipse cx="${x0 - 13}" cy="0" rx="4.5" ry="8" fill="url(#copper)" stroke="#3b1c0a" stroke-width=".6"/>
      <ellipse cx="${x0 - 13.5}" cy="0" rx="2" ry="4" fill="#1a0d05"/>
      <rect x="${x0}" y="-13" width="${len}" height="26" rx="4" fill="url(#cyl)" stroke="#3e464e" stroke-width=".6"/>
      ${foil ? `<rect x="${-len * 0.18}" y="-13" width="${len * 0.36}" height="26" fill="url(#foil)"/>
        <path d="M${-len * 0.16} -8 l5 2 l4 -3 l6 3 l5 -2 M${-len * 0.17} 2 l6 -2 l5 3 l4 -2 l6 3 M${-len * 0.15} 9 l7 -2 l5 2 l6 -3" fill="none" stroke="#fff6cf" stroke-opacity=".6" stroke-width=".6"/>` : ''}
      <rect x="${x0 + len * 0.22}" y="-13" width="3.2" height="26" fill="url(#band)"/>
      <rect x="${x0 + len * 0.7}" y="-13" width="3.2" height="26" fill="url(#band)"/>
      <rect x="${x0 + len * 0.3}" y="-17" width="10" height="5" rx="1" fill="url(#cyl)" stroke="#4b535c" stroke-width=".5"/>
      <rect x="${x0 + len * 0.55}" y="12" width="12" height="4.5" rx="1" fill="url(#cyl)" stroke="#4b535c" stroke-width=".5"/>
      <circle cx="${x0 + len * 0.82}" cy="-5" r="2.2" fill="#1b1f24" stroke="#9aa3ad" stroke-width=".5"/>
      <rect x="${x0 + len * 0.08}" y="-6" width="6" height="8" fill="#2a3037" stroke="#8b949e" stroke-width=".4"/>
      <line x1="${x0 + len * 0.4}" y1="-17" x2="${x0 + len * 0.36}" y2="-25" stroke="#c3cad2" stroke-width=".9"/>
      <circle cx="${x0 + len * 0.36}" cy="-25.5" r="1.4" fill="#e9edf1"/>
      <rect x="${x1 - 2}" y="-14" width="6" height="28" rx="2" fill="url(#band)"/>
      <ellipse cx="${x1 + 5}" cy="0" rx="6.5" ry="15" fill="#c3cad2" stroke="#4b535c" stroke-width=".7"/>
      <ellipse cx="${x1 + 5.8}" cy="0" rx="5" ry="12.5" fill="url(#dishIn)"/>
      <ellipse cx="${x1 + 4.6}" cy="-4" rx="1.6" ry="3.5" fill="#ffffff" opacity=".18"/>`);
  }
  const SPRITES = [satellite(84, false, 78, 6), satellite(62, true, 82, 7)
  ].map(svg => { const im = new Image(); im.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); return im; });
  const ORBITS = [
    { r: 1.16, tilt: 62, node: -25, period: 38, dir: 1, img: 0 },
    { r: 1.30, tilt: 28, node: 40, period: 54, dir: -1, img: 1 }
  ].map(o => ({ ...o, ci: Math.cos(o.tilt * DEG), si: Math.sin(o.tilt * DEG), cn: Math.cos(o.node * DEG), sn: Math.sin(o.node * DEG) }));
  // Position on an orbit at angle a, in globe radii: x right, y up, z toward the viewer.
  const at = (o, a) => {
    const x = Math.cos(a) * o.r, y0 = Math.sin(a) * o.r, y = y0 * o.ci, z = y0 * o.si;
    return [x * o.cn - y * o.sn, x * o.sn + y * o.cn, z];
  };
  const hidden = p => p[2] < 0 && p[0] * p[0] + p[1] * p[1] < 1;
  function size() { const d = devicePixelRatio || 1; cv.width = innerWidth * d; cv.height = innerHeight * d; }
  size(); addEventListener('resize', size);
  function frame(now) {
    requestAnimationFrame(frame);
    const d = devicePixelRatio || 1, z = map.getZoom(), alpha = Math.max(0, Math.min(1, (3.4 - z) / 0.9));
    ctx.clearRect(0, 0, cv.width, cv.height);
    if (!alpha) return;
    // Where the globe is on screen: its centre and radius, measured by projecting the view
    // centre and a point 80 degrees east of it along the surface.
    const c = map.getCenter(), lat = c.lat * DEG, dd = 80 * DEG;
    const lat2 = Math.asin(Math.sin(lat) * Math.cos(dd)), lng2 = c.lng + Math.atan2(Math.sin(dd) * Math.cos(lat), Math.cos(dd) - Math.sin(lat) * Math.sin(lat2)) / DEG;
    const p0 = map.project(c), p1 = map.project([lng2, lat2 / DEG]);
    const R = Math.hypot(p1.x - p0.x, p1.y - p0.y) / Math.sin(dd) * d, cx = p0.x * d, cy = p0.y * d;
    if (!(R > 0) || R > 4 * Math.max(cv.width, cv.height)) return;
    const scr = p => [cx + p[0] * R, cy - p[1] * R];
    ctx.globalAlpha = alpha;
    for (const o of ORBITS) {
      const ang = o.dir * now / 1000 / o.period * 2 * Math.PI, p = at(o, ang);
      if (hidden(p)) continue;
      const [x, y] = scr(p), [xn, yn] = scr(at(o, ang + o.dir * 0.02));
      const im = SPRITES[o.img];
      if (!im.complete || !im.naturalWidth) continue;
      // About a quarter of the globe's radius (the drawing fills about half its square), and a little smaller and dimmer behind it.
      const back = p[2] < 0, w = Math.max(48, Math.min(110, R / d / 4.3)) * d * (back ? 0.85 : 1);
      ctx.save();
      ctx.globalAlpha = alpha * (back ? 0.75 : 1);
      ctx.translate(x, y); ctx.rotate(Math.atan2(yn - y, xn - x));
      ctx.drawImage(im, -w / 2, -w / 2, w, w);
      ctx.restore();
    }
    ctx.globalAlpha = 1;
  }
  map.once('load', () => requestAnimationFrame(frame));
})();

/* ----- Labels and borders toggle ----- */
$('labelsChk').onchange = e => map.setLayoutProperty('labels', 'visibility', e.target.checked ? 'visible' : 'none');

/* ----- Idle auto-rotate: spins slowly when zoomed out, untouched for 6 s, and nothing is selected ----- */
let lastTouch = -Infinity, flying = false, lastFrame = performance.now();
for (const ev of ['mousedown', 'wheel', 'touchstart', 'keydown'])
  addEventListener(ev, () => { lastTouch = performance.now(); }, { passive: true, capture: true });
map.on('moveend', () => { flying = false; });
// The credits are long: they start folded behind the (i) button, so they never run under the
// fire-map bar.
map.once('load', () => {
  document.querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show');
});
// Ticking Auto-rotate starts the spin at once, even with something selected (zoomed in, it
// first zooms out). The 6-second pause only applies to later touches of the globe.
let rotateNow = false;
$('rotateChk').addEventListener('change', e => {
  rotateNow = e.target.checked;
  if (!rotateNow) return;
  lastTouch = -Infinity;
  if (map.getZoom() >= 4) { flying = true; map.easeTo({ zoom: 3, duration: 800 }); } else flying = false;
});
(function spin(t) {
  const dt = Math.min(100, t - lastFrame); lastFrame = t;
  if ($('rotateChk').checked && !drag && !flying && !selectMode && (rotateNow || (!currentBox && !currentCountry)) &&
      map.getZoom() < 4 && t - lastTouch > 6000) {
    const c = map.getCenter();
    map.setCenter([c.lng + dt * 0.004, c.lat]);       // about 4 degrees per second
  }
  requestAnimationFrame(spin);
})(lastFrame);

/* ----- Search: a country, a place name (OpenStreetMap Nominatim) or "lat, lon" ----- */
function flyWith(fn) { flying = true; lastTouch = performance.now(); fn(); }
// Everyday names for countries whose Natural Earth name is formal.
const COUNTRY_ALIASES = {
  'usa': 'United States', 'us': 'United States', 'united states of america': 'United States', 'america': 'United States',
  'uk': 'United Kingdom', 'great britain': 'United Kingdom', 'britain': 'United Kingdom', 'england': 'United Kingdom',
  'russia': 'Russian Federation', 'south korea': 'Republic of Korea', 'korea': 'Republic of Korea',
  'north korea': 'Dem. Rep. Korea', 'laos': 'Lao PDR', 'eswatini': 'Kingdom of eSwatini', 'swaziland': 'Kingdom of eSwatini',
  'drc': 'Democratic Republic of the Congo', 'dr congo': 'Democratic Republic of the Congo', 'congo': 'Republic of the Congo',
  'czechia': 'Czech Republic', 'ivory coast': "Côte d'Ivoire", 'cape verde': 'Republic of Cabo Verde', 'gambia': 'The Gambia',
  'burma': 'Myanmar', 'brunei': 'Brunei Darussalam', 'east timor': 'Timor-Leste', 'macedonia': 'North Macedonia',
  'falkland islands': 'Falkland Islands / Malvinas', 'falklands': 'Falkland Islands / Malvinas', 'micronesia': 'Federated States of Micronesia',
  'uae': 'United Arab Emirates', 'turkiye': 'Turkey', 'türkiye': 'Turkey', 'holland': 'Netherlands', 'sao tome and principe': 'São Tomé and Principe'
};
const plain = t => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
async function countryNamed(q) {
  const list = await loadCountries(), key = plain(q);
  const alias = COUNTRY_ALIASES[key] || COUNTRY_ALIASES[q.toLowerCase().trim()];
  if (alias) return list.find(c => c.n === alias);
  return list.find(c => plain(c.n) === key) ||
    (key.length >= 4 ? list.filter(c => plain(c.n).startsWith(key)).sort((a, b) => a.n.length - b.n.length)[0] : undefined);
}
// Frame the main landmass (its biggest polygon), so Russia or Fiji do not zoom out to the whole world.
function countryFrame(c) {
  let best = null, bestA = -1;
  for (const poly of c.p) {
    const r = poly[0], xs = r.map(p => p[0]), ys = r.map(p => p[1]);
    const b = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)], a = (b[2] - b[0]) * (b[3] - b[1]);
    if (a > bestA) { bestA = a; best = b; }
  }
  return c.b[2] - c.b[0] > 180 ? best : c.b;
}
function goToCountry(c) {
  $('searchResults').textContent = '';
  $('search').value = c.n;
  const [w, s, e, n] = countryFrame(c);
  flying = true;
  selectCountry(c);
  // The panel opens with a short camera move of its own; fly once it is done, or it would cancel ours.
  setTimeout(() => flyWith(() => map.fitBounds([[w, s], [e, n]], { padding: 60, maxZoom: 6 })), 350);
}
$('search').addEventListener('keydown', async e => {
  if (e.key !== 'Enter') return;
  const q = e.target.value.trim(), list = $('searchResults');
  list.textContent = '';
  if (!q) return;
  const m = q.match(/^(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)$/);
  if (m && Math.abs(+m[1]) <= 90 && Math.abs(+m[2]) <= 180) {
    flyWith(() => map.flyTo({ center: [+m[2], +m[1]], zoom: 13 }));
    return;
  }
  const named = await countryNamed(q);
  if (named) { goToCountry(named); return; }
  const li = msg => { const x = document.createElement('li'); x.textContent = msg; list.append(x); return x; };
  try {
    const r = await fetch('https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&q=' + encodeURIComponent(q));
    const hits = await r.json();
    if (!hits.length) { li('No place found'); return; }
    // A country written in another way (or another language): pick it by where Nominatim puts it.
    const top = hits[0];
    if (top.addresstype === 'country') {
      const c = await countryAt({ lng: +top.lon, lat: +top.lat });
      if (c) { goToCountry(c); return; }
    }
    for (const h of hits) {
      li(h.display_name).onclick = () => {
        list.textContent = '';
        const [s, n, w, ea] = h.boundingbox.map(Number);
        flyWith(() => map.fitBounds([[w, s], [ea, n]], { padding: 80, maxZoom: 16 }));
      };
    }
  } catch { li('Search is unavailable right now'); }
});

/* ================= 4. Data ================= */
// Data layout (written by tools/build_world.py): the world is cut into 10-degree blocks,
// each block into 1-degree tiles, and busy tiles into k x k cells. Monthly totals exist at
// every level, so only the pieces cut by the selection's edge are read hotspot by hotspot.
const data = { index: null, blockList: [], dayMonth: null, era: null, error: null };
const REC = 9;                          // bytes per hotspot: lat u16, lon u16, day u16, frp u16, flags u8

// Files read whole (not by byte range) are also published gzip-compressed (name + ".gz", made by
// tools/deploy.sh): about 3x smaller to download, unpacked here by the browser. If the .gz copy
// is missing (local copy of the app) or the browser cannot unpack it, the plain file is read.
async function fetchWhole(url) {
  if (typeof DecompressionStream === 'function') {
    try {
      const r = await fetch(url + '.gz');
      if (r.ok) return await new Response(r.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
    } catch { /* fall back to the plain file */ }
  }
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + ': HTTP ' + r.status);
  return r.arrayBuffer();
}

const ready = (async () => {
  const r = await fetch('data/meta.json');
  if (!r.ok) throw new Error('data/meta.json not found');
  const ix = data.index = await r.json(), M = ix.months;
  if (!(ix.version >= 3)) throw new Error('data/ was made by an older tools/build_world.py: rebuild it');
  const cb = await fetchWhole('data/coarse.bin');
  data.blockList = ix.blocks.map(([la, lo], i) => ({
    la, lo, key: `${la}_${lo}`, tiles: null,
    mod: new Uint32Array(cb, i * 16 * M, M), vii: new Uint32Array(cb, i * 16 * M + 4 * M, M),
    harm: new Float32Array(cb, i * 16 * M + 8 * M, M), harmM: new Float32Array(cb, i * 16 * M + 12 * M, M)
  }));
  // Lookup: day number since 2000-01-01 -> month number since 2000-01.
  const nDays = Math.ceil(M * 31) + 62;
  data.dayMonth = new Uint16Array(nDays);
  for (let d = 0; d < nDays; d++) {
    const dt = new Date(Date.UTC(2000, 0, 1 + d));
    data.dayMonth[d] = (dt.getUTCFullYear() - 2000) * 12 + dt.getUTCMonth();
  }
  data.era = Uint8Array.from({ length: M }, (_, m) => +(m >= ix.viirsStart && m <= ix.viirsEnd));
  // VIIRS outage days (filled with converted MODIS): per 10-degree block, the days concerned,
  // and the months for which tile files carry extra per-cell counts.
  data.gaps = new Map(Object.entries(ix.gaps || {}).map(([k, days]) => [k, new Set(days)]));
  data.gapIdx = new Int16Array(M).fill(-1);
  (ix.gapMonths || []).forEach((m, i) => { data.gapIdx[m] = i; });
  const [fy, fm] = ix.firstDate.split('-').map(Number);
  const [ly, lm, ld] = ix.lastDate.split('-').map(Number);
  ix.firstMonth = (fy - 2000) * 12 + fm - 1;
  ix.lastMonth = M - 1;
  ix.partialMonth = -1;
  // If the newest data stops mid-month, that month is not shown anywhere (map, table, charts,
  // downloads) until it is complete: the record ends with the last complete month.
  if (ld < new Date(Date.UTC(ly, lm, 0)).getUTCDate() && ix.lastMonth > ix.firstMonth) {
    ix.lastMonth--;
    ix.lastDate = new Date(Date.UTC(ly, lm - 1, 0)).toISOString().slice(0, 10);
  }
})().catch(e => { data.error = e; });

// Fetch only bytes [start, end) of a file. Falls back to the whole file if the server
// does not support partial requests.
async function fetchRange(url, start, end) {
  const r = await fetch(url, { headers: { Range: `bytes=${start}-${end - 1}` } });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  const buf = await r.arrayBuffer();
  return r.status === 206 ? buf : buf.slice(start, end);
}
const inViirsEra = m => data.era[m] === 1;
// The outage days of the 10-degree block a tile belongs to (null when it has none).
const gapsOf = t => (t.gap !== undefined ? t.gap : (t.gap = data.gaps.get(`${Math.floor(t.la / 10) * 10}_${Math.floor(t.lo / 10) * 10}`) || null));
// Does a hotspot of tile t seen on this day (in month m) count as VIIRS-era? Not on an outage day.
const viirsDay = (t, day, m) => data.era[m] === 1 && !(gapsOf(t) && t.gap.has(day));

// A block file: its tiles (position, cell split k, hotspot count), then per tile the four monthly
// series: MODIS count, VIIRS count, VIIRS-scale value, MODIS-scale value.
function loadBlock(blk) {
  if (!blk.tiles) blk.tiles = fetchWhole(`data/blocks/${blk.key}.bin`).then(buf => {
    const M = data.index.months, dv = new DataView(buf), n = dv.getUint32(0, true), S = 4 + 12 * n;
    return Array.from({ length: n }, (_, i) => {
      const o = 4 + 12 * i, la = dv.getInt16(o, true), lo = dv.getInt16(o + 2, true), q = S + i * 16 * M;
      return { la, lo, key: `${la}_${lo}`, k: dv.getUint16(o + 4, true), n: dv.getUint32(o + 8, true), head: null, fac: null, F: null,
        mod: new Uint32Array(buf, q, M), vii: new Uint32Array(buf, q + 4 * M, M),
        harm: new Float32Array(buf, q + 8 * M, M), harmM: new Float32Array(buf, q + 12 * M, M) };
    });
  });
  return blk.tiles;
}
// A split tile starts with a directory (where each cell's hotspots begin) and per-cell monthly
// series: MODIS and VIIRS counts, then the two scales stored as round(64 * sqrt(value)).
function loadHead(t) {
  if (!t.head) {
    const k2 = t.k * t.k, M = data.index.months, a = 4 * (k2 + 1), n = k2 * M, len = a + 8 * n;
    t.head = fetchRange(`data/tiles/${t.key}.bin`, 0, len).then(buf => ({
      len, dir: new Uint32Array(buf, 0, k2 + 1),
      mod: new Uint16Array(buf, a, n), vii: new Uint16Array(buf, a + 2 * n, n),
      hv: new Uint16Array(buf, a + 4 * n, n), hm: new Uint16Array(buf, a + 6 * n, n)
    }));
  }
  return t.head;
}
const unpack = u => u * u / 4096;
// The weights of a tile's hotspots, needed when they are read one by one: n, then n sorted keys
// ((quarter-degree cell * months + month) * 16 + kind), then n weights. Kinds 0-3: a MODIS
// hotspot on the VIIRS scale when VIIRS is not there (kept * 2 + night, kept = type 0 and
// confidence nominal or high); kinds 4-9: on the MODIS scale (4 + satellite * 2 + night).
function loadFactors(t) {
  if (!t.fac) t.fac = fetch(`data/factors/${t.key}.bin`).then(r => (r.ok ? r.arrayBuffer() : null)).then(buf => {
    const n = buf && buf.byteLength >= 4 ? new Uint32Array(buf, 0, 1)[0] : 0;
    return (t.F = { n, k: new Uint32Array(n ? buf : 0, n ? 4 : 0, n), v: new Float32Array(n ? buf : 0, n ? 4 + 4 * n : 0, n) });
  });
  return t.fac;
}
function factor(F, key) {
  let a = 0, b = F.n - 1;
  while (a <= b) { const c = (a + b) >> 1, k = F.k[c]; if (k === key) return F.v[c]; if (k < key) a = c + 1; else b = c - 1; }
  return 0;
}
// What one hotspot of tile t counts for on the two scales (the data build's rules; loadFactors(t)
// first). VIIRS scale: a VIIRS hotspot counts 1, a MODIS hotspot only when VIIRS was not there.
// MODIS scale: only the satellite the month is taken from counts; in months after the team's
// VIIRS-to-MODIS tables end, Aqua stands in for VIIRS on VIIRS outage days.
const W = { v: 0, m: 0 };
function pointWeights(t, la, lo, day, m, fl) {
  const sat = fl & 3, night = fl >> 2 & 1, kept = (fl >> 3 & 3) === 0 && (fl >> 5 & 3) >= 1 ? 2 : 0, vd = viirsDay(t, day, m);
  const base = ((((la * 4) >> 16) * 4 + ((lo * 4) >> 16)) * data.index.months + m) * 16;
  W.v = sat === 2 ? +vd : vd ? 0 : factor(t.F, base + kept + night);
  W.m = m > data.index.modisScale.last && gapsOf(t) && t.gap.has(day) ? +(sat === 1) : factor(t.F, base + 4 + sat * 2 + night);
  return W;
}
// A selection that crosses the antimeridian is handled as two ordinary boxes.
const boxesOf = s => s.east >= s.west ? [s] : [{ ...s, east: 180 }, { ...s, west: -180 }];
// 0 = square outside the box, 1 = cut by its edge, 2 = fully inside.
function relation(lo, la, size, b) {
  if (lo + size <= b.west || lo >= b.east || la + size <= b.south || la >= b.north) return 0;
  return lo >= b.west && lo + size <= b.east && la >= b.south && la + size <= b.north ? 2 : 1;
}
// Selection edges in the tile's 0..65535 integer units.
function tileWindow(tile, b) {
  const u = v => Math.max(-1, Math.min(65536, v * 65535));
  return { s: u(b.south - tile.la), n: u(b.north - tile.la), w: u(b.west - tile.lo), e: u(b.east - tile.lo) };
}
async function pool(items, limit, fn) {
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (i < items.length) await fn(items[i++]);
  }));
}

// A region answers two questions: how a square relates to it (0 outside, 1 cut by its
// edge, 2 fully inside) and, for a square cut by the edge, which hotspots are inside.
const BAND = 0.02;                       // latitude band height for the polygon index, degrees
function polygonRegion(c) {
  // Index the border segments by latitude band so each test only looks at nearby segments.
  const [w, s, e, n] = c.b, nb = Math.max(1, Math.ceil((n - s) / BAND)), bands = Array.from({ length: nb }, () => []);
  const band = y => Math.max(0, Math.min(nb - 1, Math.floor((y - s) / BAND)));
  for (const poly of c.p) for (const r of poly) for (let i = 0; i < r.length - 1; i++) {
    const seg = [r[i][0], r[i][1], r[i + 1][0], r[i + 1][1]];
    for (let k = band(Math.min(seg[1], seg[3])), k1 = band(Math.max(seg[1], seg[3])); k <= k1; k++) bands[k].push(seg);
  }
  const inside = (x, y) => {
    if (x < w || x > e || y < s || y > n) return false;
    let c2 = false;
    for (const [x1, y1, x2, y2] of bands[band(y)])
      if ((y1 > y) !== (y2 > y) && x < x1 + (y - y1) * (x2 - x1) / (y2 - y1)) c2 = !c2;
    return c2;
  };
  return {
    rel(lo, la, size) {
      if (lo > e || lo + size < w || la > n || la + size < s) return 0;
      for (let k = band(la), k1 = band(la + size); k <= k1; k++)
        for (const [x1, y1, x2, y2] of bands[k])
          if (Math.min(x1, x2) <= lo + size && Math.max(x1, x2) >= lo && Math.min(y1, y2) <= la + size && Math.max(y1, y2) >= la) return 1;
      return inside(lo + size / 2, la + size / 2) ? 2 : 0;
    },
    filter: t => (la, lo) => inside(t.lo + lo / 65535, t.la + la / 65535)
  };
}
function regionOf(sel) {
  if (!sel._region) {
    let r;
    if (sel.poly) r = polygonRegion(sel.poly);
    else {
      const boxes = boxesOf(sel);
      r = {
        rel: (lo, la, size) => boxes.reduce((best, b) => Math.max(best, relation(lo, la, size, b)), 0),
        filter: t => {
          const ws = boxes.map(b => tileWindow(t, b));
          return (la, lo) => ws.some(w => la >= w.s && la < w.n && lo >= w.w && lo < w.e);
        }
      };
    }
    Object.defineProperty(sel, '_region', { value: r });
  }
  return sel._region;
}

// Visit everything inside the selection. Squares fully inside are reported through
// h.series / h.cell (stored totals) unless wantPoints is set; everything else, and
// everything when wantPoints is set, is delivered hotspot by hotspot through h.points,
// with keep(la, lo) telling which of them are inside (null = all of them).
async function walk(sel, wantPoints, h, onProgress) {
  const R = regionOf(sel), jobs = [];
  let hit = 0;
  for (const blk of data.blockList) {
    const rb = R.rel(blk.lo, blk.la, 10);
    if (!rb) continue;
    hit++;
    if (rb === 2 && !wantPoints) { h.series(blk.mod, blk.vii, blk.harm, blk.harmM); continue; }
    for (const t of await loadBlock(blk)) {
      const rt = rb === 2 ? 2 : R.rel(t.lo, t.la, 1);
      if (!rt) continue;
      if (rt === 2 && !wantPoints) { h.series(t.mod, t.vii, t.harm, t.harmM); continue; }
      const keep = rt === 2 ? null : R.filter(t);
      if (t.k === 1) { jobs.push({ t, start: 0, end: t.n * REC, keep }); continue; }
      const head = await loadHead(t), k = t.k, size = 65536 / k;
      let run = -1;
      for (let c = 0; c <= k * k; c++) {
        let need = false;
        if (c < k * k) {
          const y0 = Math.floor(c / k) * size, x0 = (c % k) * size;
          // Cell bounds in degrees, padded by one storage unit so the test errs on the side of reading points.
          const rc = rt === 2 ? 2 : R.rel(t.lo + x0 / 65535, t.la + y0 / 65535, (size + 1) / 65535);
          if (rc === 2 && !wantPoints) h.cell(t, head, c);
          else if (rc) need = head.dir[c + 1] > head.dir[c];
        }
        if (need && run < 0) run = c;
        if (!need && run >= 0) { jobs.push({ t, start: head.len + head.dir[run] * REC, end: head.len + head.dir[c] * REC, keep }); run = -1; }
      }
    }
  }
  let done = 0;
  await pool(jobs, 8, async j => {
    const [buf] = await Promise.all([fetchRange(`data/tiles/${j.t.key}.bin`, j.start, j.end), loadFactors(j.t)]);
    h.points(j.t, new DataView(buf), Math.floor(buf.byteLength / REC), j.keep);
    if (onProgress) onProgress(++done, jobs.length);
  });
  return hit;
}

// Monthly totals of every country, worked out in advance (see precomputeCountries below), so a
// country click is instant online instead of reading hundreds of files along its border.
// Layout: n countries, M months, total hotspots (to spot an out-of-date file), then for each
// country four runs of M floats: MODIS count, VIIRS count, VIIRS-scale value, MODIS-scale value.
let countryTotalsP = null;
function loadCountryTotals() {
  if (!countryTotalsP) countryTotalsP = fetchWhole('data/countries.bin').catch(() => null).then(buf => {
    if (!buf || buf.byteLength < 16) return null;
    const dv = new DataView(buf), n = dv.getUint32(0, true), M = dv.getUint32(4, true);
    if (M !== data.index.months || dv.getFloat64(8, true) !== data.index.hotspots || buf.byteLength !== 16 + n * 4 * M * 4) return null;
    return i => (i < n ? new Float32Array(buf, 16 + i * 4 * M * 4, 4 * M) : null);
  }).catch(() => null);
  return countryTotalsP;
}
let precomputing = false;

/* ----- Units: every month counted as VIIRS (375 m pixels) or as MODIS (1 km pixels) would see it ----- */
// Both records come ready from the data build (tools/build_world.py), which gives every hotspot
// a weight on each scale from the team's two models; the app only adds weights up.
// vEq: before Feb 2012, MODIS converted to VIIRS (Louis's MODIS-to-VIIRS model); from Feb 2012
//      VIIRS itself (outage days filled with converted MODIS).
// mEq: what MODIS on Aqua would count (Ianis's VIIRS-to-MODIS model): Aqua's own counts from
//      July 2002 to 2021, Terra converted to Aqua before, VIIRS converted to Aqua from 2022.
const UNITS = {
  vEq: { name: 'VIIRS', px: '375 m', long: 'VIIRS-equivalent hotspots' },
  mEq: { name: 'MODIS', px: '1 km', long: 'MODIS Aqua-equivalent hotspots' }
};

async function query(sel, onProgress) {
  const ix = data.index, M = ix.months, era = data.era;
  const out = { modis: new Float64Array(M), viirs: new Float64Array(M), raw: new Float64Array(M),
    vEq: new Float64Array(M), mEq: new Float64Array(M), tiles: 0 };
  if (sel.poly && sel.poly.i !== undefined && !precomputing) {
    const get = await loadCountryTotals(), f = get && get(sel.poly.i);
    if (f) {
      for (let m = 0; m < M; m++) {
        out.modis[m] = f[m]; out.viirs[m] = f[M + m]; out.vEq[m] = f[2 * M + m]; out.mEq[m] = f[3 * M + m];
        out.raw[m] = era[m] ? out.viirs[m] : out.modis[m];
      }
      out.tiles = out.vEq.some(v => v > 0) || out.mEq.some(v => v > 0) ? 1 : 0;
      return out;
    }
  }
  out.tiles = await walk(sel, false, {
    series(mod, vii, hv, hm) {
      for (let m = 0; m < M; m++) {
        out.modis[m] += mod[m]; out.viirs[m] += vii[m]; out.raw[m] += era[m] ? vii[m] : mod[m];
        out.vEq[m] += hv[m]; out.mEq[m] += hm[m];
      }
    },
    cell(t, head, c) {
      for (let m = 0, o = c * M; m < M; m++, o++) {
        const mod = head.mod[o], v = head.vii[o];
        out.modis[m] += mod; out.viirs[m] += v; out.raw[m] += era[m] ? v : mod;
        out.vEq[m] += unpack(head.hv[o]); out.mEq[m] += unpack(head.hm[o]);
      }
    },
    points(t, dv, n, keep) {
      for (let i = 0, o = 0; i < n; i++, o += REC) {
        const la = dv.getUint16(o, true), lo = dv.getUint16(o + 2, true);
        if (keep && !keep(la, lo)) continue;
        const day = dv.getUint16(o + 4, true), m = data.dayMonth[day], fl = dv.getUint8(o + 8), w = pointWeights(t, la, lo, day, m, fl);
        if ((fl & 3) === 2) { out.viirs[m]++; if (era[m]) out.raw[m]++; } else { out.modis[m]++; if (!era[m]) out.raw[m]++; }
        out.vEq[m] += w.v; out.mEq[m] += w.m;
      }
    }
  }, onProgress);
  return out;
}

/* ----- Fire map: month slider + year box drive a red heat layer on the globe ----- */
// Two levels of detail: the whole world in 0.25 degree cells when zoomed out, and
// 0.05 degree cells for the 10-degree blocks in view when zoomed in.
const heat = { token: 0, shown: '', heads: new Map() };
const HEAT_PAINT = {
  world: { w: 8, radius: ['interpolate', ['exponential', 2], ['zoom'], 0, 1.5, 2, 2.5, 4, 6, 6, 22] },
  detail: { w: 7, radius: ['interpolate', ['exponential', 2], ['zoom'], 4, 3, 7, 12, 10, 90] }
};
function heatBlocks() {
  if (map.getZoom() < 4.6) return null;
  // Blocks that overlap the part of the globe on screen (the view may cross the 180° line).
  const b = map.getBounds(), west = b.getWest(), span = Math.min(360, b.getEast() - west);
  const near = data.blockList.filter(k => k.la + 10 > b.getSouth() && k.la < b.getNorth() &&
    (((k.lo - west) % 360 + 360) % 360 < span || ((west - k.lo) % 360 + 360) % 360 < 10));
  return near.length && near.length <= 24 ? near : null;
}
// World fire-map files, kept in memory so an animation can run smoothly (about 0.3 MB each).
const heat0Cache = new Map();
function getHeat0(m) {
  if (!heat0Cache.has(m)) {
    if (heat0Cache.size > 60) heat0Cache.delete(heat0Cache.keys().next().value);
    heat0Cache.set(m, fetchWhole(`data/heat0/${m}.bin`));
  }
  return heat0Cache.get(m);
}
// Each map cell keeps its VIIRS-scale value (v, which sets the colour scale) and its value in
// the chosen units (w). Both come from the data build.
async function heatFeatures(m, blocks) {
  const ix = data.index, feats = [], modis = state.unit === 'mEq';
  const push = (x, y, v, vm) => feats.push({ type: 'Feature', properties: { w: modis ? vm : v, v }, geometry: { type: 'Point', coordinates: [x, y] } });
  if (!blocks) {
    const dv = new DataView(await getHeat0(m));
    for (let o = 0; o + 12 <= dv.byteLength; o += 12)
      push((dv.getUint16(o, true) + 0.5) * ix.heat0 - 180, (dv.getUint16(o + 2, true) + 0.5) * ix.heat0 - 90,
        dv.getFloat32(o + 4, true), dv.getFloat32(o + 8, true));
    return feats;
  }
  await pool(blocks, 6, async blk => {
    const url = `data/heat1/${blk.key}.bin`, hl = 4 * (ix.months + 1);
    if (!heat.heads.has(blk.key)) heat.heads.set(blk.key, fetchRange(url, 0, hl).then(b => new Uint32Array(b)));
    const offs = await heat.heads.get(blk.key);
    if (offs[m + 1] === offs[m]) return;
    const dv = new DataView(await fetchRange(url, hl + offs[m] * 6, hl + offs[m + 1] * 6));
    for (let o = 0; o + 6 <= dv.byteLength; o += 6)
      push(blk.lo + (dv.getUint8(o) + 0.5) * ix.heat1, blk.la + (dv.getUint8(o + 1) + 0.5) * ix.heat1,
        dv.getUint16(o + 2, true) / 8, dv.getUint16(o + 4, true) / 8);
  });
  return feats;
}
async function showHeat() {
  const ix = data.index, on = $('heatChk').checked;
  const year = +$('heatYear').value, moy = +$('heatMonth').value, m = (year - 2000) * 12 + moy;
  [...$('monthTicks').children].forEach((s, i) => s.classList.toggle('on', i === moy));
  const hasData = on && m >= ix.firstMonth && m <= ix.lastMonth;
  const blocks = hasData ? heatBlocks() : null;
  const want = !hasData ? 'none' : m + ':' + (blocks ? blocks.map(b => b.key).join(',') : 'world');
  if (want === heat.shown) return;                 // nothing changed (e.g. the globe only rotated)
  const token = ++heat.token;
  heat.shown = want;
  // Slightly mute the satellite colours while the fire map is on, so the reds stand out.
  map.setPaintProperty('imagery', 'raster-saturation', on ? -0.25 : 0);
  let note = 'no satellite data', feats = [];
  if (hasData) {
    try { feats = await heatFeatures(m, blocks); } catch { feats = []; }
    if (token !== heat.token) return;
    const total = data.blockList.reduce((a, b) => a + (state.unit === 'mEq' ? b.harmM : b.harm)[m], 0);
    note = total;
    const p = blocks ? HEAT_PAINT.detail : HEAT_PAINT.world;
    // Strength relative to the busiest places this month (99th percentile), square-rooted so
    // medium activity still shows: quiet areas glow dark red, the busiest ones yellow.
    // The scale always comes from the VIIRS-unit weights, so switching to MODIS units shows how
    // much less MODIS detects (and where) instead of rescaling it to look the same.
    const ws = feats.map(f => f.properties.v).filter(v => v > 0).sort((a, b) => a - b);
    // While the animation plays, one fixed scale for every month, so quiet months look
    // quiet and big fire seasons stand out; otherwise each month uses its own scale.
    const p99 = play.on && play.scale && !blocks ? play.scale : (ws.length ? ws[Math.floor(ws.length * 0.99)] || 1 : 1);
    map.setPaintProperty('heat', 'heatmap-weight', ['min', 1, ['sqrt', ['/', ['get', 'w'], p99]]]);
    map.setPaintProperty('heat', 'heatmap-radius', p.radius);
  }
  map.getSource('heat').setData({ type: 'FeatureCollection', features: feats });
  // The running month is marked next to its name, where it cannot be cut off.
  $('heatWhen').textContent = `${MONTHS_LONG[moy]} ${year}` + (hasData && m === ix.partialMonth ? ', so far' : '');
  heat.total = hasData ? note : null;
  updateMapArea();
}
/* ----- Showing one month of the record on the map (a click on the table or the monthly chart) ----- */
function mapMonth() { return (+$('heatYear').value - 2000) * 12 + +$('heatMonth').value; }
// Where a month's number comes from, in the chosen units.
function sourceOf(m) {
  const ix = data.index;
  return state.unit === 'vEq' ? (inViirsEra(m) ? 'VIIRS data' : 'MODIS data converted to VIIRS')
    : m < ix.aquaStart ? 'Terra data converted to Aqua' : m < ix.modisScale.viirsFrom ? 'Aqua data' : 'VIIRS data converted to Aqua';
}
function showMonthOnMap(m) {
  if (play.on) stopPlay();
  $('heatChk').checked = true;
  $('heatYear').value = 2000 + Math.floor(m / 12);
  $('heatMonth').value = m % 12;
  if (phone()) openPanel(false);                     // phone: show the globe and the bar with the numbers
  showHeat();
}
// Under the world total: the selected area's own number for the month on the map, and its source.
// Two lines under the month: the numbers (selected area first, then the world), then the units
// and, for a selection, where that month's number comes from.
function updateMapArea() {
  const m = mapMonth(), r = state.result, cap = $('heatCaption'), sub = $('heatArea');
  const on = $('heatChk').checked, total = heat.total;
  const area = on && total != null && r && state.sel;
  // For a selection: how this month compares with the same month in the other years (the
  // Anomaly view's number), when the month is inside the dates chosen in the panel.
  const md = state.model, moy = m % 12, v = area ? r[state.unit][m] : 0;
  const inRange = area && md && m >= state.m0 && m <= state.m1 && md.med[moy] > 0 && m !== data.index.partialMonth;
  const vsUsual = inRange ? ` · ${pct((v - md.med[moy]) / md.med[moy] * 100)} vs a usual ${MONTHS_LONG[moy]}` : '';
  cap.textContent = !on ? 'Fire map hidden' : total == null ? 'No satellite data'
    : area ? `${state.sel.country || 'Selected area'} ${nf(v)}${vsUsual}` : `World ${nf(Math.round(total))}`;
  sub.hidden = !on || total == null;
  sub.textContent = area ? `World ${nf(Math.round(total))} · ${UNITS[state.unit].long} · ${sourceOf(m)}` : UNITS[state.unit].long;
  markMapMonth();
}
// The table cell of the month on the map is outlined, whichever way the month was chosen.
function markMapMonth() {
  const m = String(mapMonth());
  for (const td of document.querySelectorAll('#cal td.c')) td.classList.toggle('now', td.dataset.m === m);
}
$('cal').addEventListener('click', e => {
  const td = e.target.closest('td.c');
  if (td) showMonthOnMap(+td.dataset.m);
});

/* ----- Play: the world's fire map month by month, from the first to the last month ----- */
// About 6 months per second: the whole record (Nov 2000 to today) plays in under a minute.
const play = { on: false, timer: 0, scale: null, speed: 2 };
const MS_PER_MONTH = 350;
async function playScale() {
  if (play.scale) return play.scale;
  // The scale comes from the busiest month on record, so every month is drawn against it.
  const M = data.index.months, tot = new Float64Array(M);
  for (const b of data.blockList) for (let m = 0; m < M; m++) tot[m] += b.harm[m];
  const busiest = tot.indexOf(Math.max(...tot));
  const dv = new DataView(await getHeat0(busiest)), ws = [];
  for (let o = 0; o + 12 <= dv.byteLength; o += 12) { const v = dv.getFloat32(o + 4, true); if (v > 0) ws.push(v); }
  ws.sort((a, b) => a - b);
  return (play.scale = ws[Math.floor(ws.length * 0.99)] || 1);
}
function stopPlay() {
  play.on = false;
  clearTimeout(play.timer);
  $('playBtn').innerHTML = ICON_PLAY + '<span class="lbl">Play</span>';
  $('playBtn').setAttribute('aria-label', 'Play');
  $('playBtn').setAttribute('aria-pressed', 'false');
  heat.shown = '';
  showHeat();                                     // back to the month's own colour scale
}
async function startPlay() {
  const ix = data.index;
  let m = (+$('heatYear').value - 2000) * 12 + +$('heatMonth').value;
  if (m >= ix.lastMonth) m = ix.firstMonth;        // at the end: start again from the beginning
  play.on = true;
  $('playBtn').innerHTML = ICON_PAUSE + '<span class="lbl">Pause</span>';
  $('playBtn').setAttribute('aria-label', 'Pause');
  $('playBtn').setAttribute('aria-pressed', 'true');
  $('heatChk').checked = true;
  await playScale();
  const tick = async () => {
    if (!play.on) return;
    const t0 = performance.now();
    $('heatYear').value = 2000 + Math.floor(m / 12);
    $('heatMonth').value = m % 12;
    getHeat0(m + 1); getHeat0(m + 2);              // fetch the next months ahead of time
    await showHeat();
    if (!play.on) return;
    if (m >= ix.lastMonth) { stopPlay(); return; }
    m++;
    play.timer = setTimeout(tick, Math.max(0, MS_PER_MONTH / play.speed - (performance.now() - t0)));
  };
  tick();
}

Promise.all([ready, new Promise(res => map.once('load', res))]).then(() => {
  if (data.error) { $('heatCaption').textContent = 'Fire map data could not be loaded'; return; }
  $('playBtn').onclick = () => (play.on ? stopPlay() : startPlay());
  const ix = data.index, fy = 2000 + Math.floor(ix.firstMonth / 12), ly = 2000 + Math.floor(ix.lastMonth / 12);
  // Start on the newest month, even while it is still running (its caption says "incomplete month").
  const startM = ix.lastMonth;
  const yearBox = $('heatYear'), slider = $('heatMonth');
  yearBox.min = fy; yearBox.max = ly; yearBox.value = 2000 + Math.floor(startM / 12);
  slider.value = startM % 12;
  MONTHS.forEach((mn, i) => {
    const s = document.createElement('span');
    s.textContent = mn;
    s.onclick = () => { if (play.on) stopPlay(); slider.value = i; showHeat(); };
    $('monthTicks').append(s);
  });
  slider.oninput = () => { if (play.on) stopPlay(); showHeat(); };
  $('heatChk').onchange = showHeat;
  // Typing a year: update as soon as it is a valid year; tidy it when the box is left.
  yearBox.oninput = () => { if (play.on) stopPlay(); const y = +yearBox.value; if (Number.isInteger(y) && y >= fy && y <= ly) showHeat(); };
  yearBox.onchange = () => { yearBox.value = Math.max(fy, Math.min(ly, Math.round(+yearBox.value) || ly)); showHeat(); };
  // Moving or zooming the globe can change which level of detail is needed.
  let moveTimer = 0;
  map.on('moveend', () => { clearTimeout(moveTimer); moveTimer = setTimeout(showHeat, 250); });
  showHeat();
});

/* ================= 5. Panel ================= */
// m0..m1: the chosen date range, as month numbers since January 2000; y0..y1 are its years.
const state = { sel: null, result: null, unit: 'vEq', view: 'count', m0: 0, m1: 0, y0: 0, y1: 0, model: null, token: 0 };
const fullYears = () => state.m0 % 12 === 0 && state.m1 % 12 === 11;
const monthName = m => `${MONTHS[m % 12]} ${2000 + Math.floor(m / 12)}`;
const rangeLabel = () => fullYears() ? (state.y0 === state.y1 ? `${state.y0}` : `${state.y0}–${state.y1}`) : `${monthName(state.m0)} – ${monthName(state.m1)}`;

const nf = (v, d = 0) => v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
function compact(v) {
  v = Math.round(v);
  if (v < 1000) return String(v);
  if (v < 10000) return (v / 1000).toFixed(1) + 'k';
  if (v < 1e6) return Math.round(v / 1000) + 'k';
  return (v / 1e6).toFixed(v < 1e7 ? 1 : 0) + 'M';
}
const fmtArea = a => a < 1e6 ? nf(a) + ' m²' : nf(a / 1e6, a < 1e9 ? 1 : 0) + ' km²';
const pct = p => (p > 0 ? '+' : p < 0 ? '−' : '') + nf(Math.abs(p)) + '%';
function quantile(sorted, q) {
  if (!sorted.length) return 0;
  const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

// Colour ramps. Sequential: one red hue, dark (few) to light (many), log scale.
// Diverging: blue (below normal) - grey (normal) - red (above normal).
// Fire scale, like glowing embers: dark red (few) -> red -> orange -> yellow (many).
const SEQ = ['#4a0d06', '#8a1609', '#c4240d', '#e8471a', '#f37a22', '#f9a72f', '#fdd23f', '#fff07a'];
// Dark text on the bright (orange/yellow) cells, light text on the dark red ones.
const textOn = rgb => { const [r, g, b] = rgb.match(/\d+/g).map(Number); return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#0b0b0b' : '#f0efec'; };
const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const mix = (a, b, t) => { const A = hex(a), B = hex(b); return 'rgb(' + A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(',') + ')'; };
function seqColor(t, ramp = SEQ) {
  const x = Math.max(0, Math.min(1, t)) * (ramp.length - 1), i = Math.min(ramp.length - 2, Math.floor(x));
  return mix(ramp[i], ramp[i + 1], x - i);
}
const divColor = d => mix('#383835', d < 0 ? '#3987e5' : '#e66767', Math.min(1, Math.abs(d)));
// Anomaly on a log scale: -1 means a quarter of normal or less, +1 means four times normal or more.
const anomScore = (v, med) => Math.max(-1, Math.min(1, Math.log2((v + 1) / (med + 1)) / 2));

function setStatus(msg) { $('status').hidden = !msg; $('status').textContent = msg || ''; }
function openPanel(open) {
  if (!open || !$('panel').classList.contains('open')) setSheetFull(false);   // a sheet always opens at half height
  $('panel').classList.toggle('open', open);
  $('panelTab').classList.toggle('show', !open && !!state.sel);
  // Keep the globe's centre in the part of the screen the panel leaves free: on the right of a
  // wide screen, above the bottom sheet on a phone.
  const wide = innerWidth > 760, w = open && wide ? $('panel').offsetWidth + 12 : 0, h = open && !wide ? innerHeight * 0.58 : 0;
  map.easeTo({ padding: { top: 0, bottom: h, left: 0, right: w }, duration: 300 });
}
$('panelClose').onclick = () => openPanel(false);

/* ----- Phone: the panel is a bottom sheet, half height or full height ----- */
const phone = () => innerWidth <= 760;
function setSheetFull(full) {
  $('panel').classList.toggle('full', full);
  $('sheetHandle').setAttribute('aria-expanded', full);
  $('sheetHandle').setAttribute('aria-label', full ? 'Show less of the results' : 'Show more of the results');
}
let sheetSwiped = false;                             // a swipe on the handle is not also a tap
$('sheetHandle').onclick = () => {
  if (sheetSwiped) { sheetSwiped = false; return; }
  setSheetFull(!$('panel').classList.contains('full'));
};
// Reading on (scrolling the results) opens the sheet to full height.
$('scroll').addEventListener('scroll', e => {
  if (phone() && e.target.scrollTop > 24 && !$('panel').classList.contains('full')) setSheetFull(true);
}, { passive: true });
// Swipe on the sheet's top: up for full height, down for half height, down again to hide.
(() => {
  let y0 = null;
  const start = e => { if (phone() && !e.target.closest('#panelClose')) y0 = e.clientY; };
  const end = e => {
    if (y0 === null) return;
    const dy = e.clientY - y0, full = $('panel').classList.contains('full');
    y0 = null;
    sheetSwiped = Math.abs(dy) > 30 && e.currentTarget === $('sheetHandle');
    if (dy < -30) setSheetFull(true);
    else if (dy > 30) full ? setSheetFull(false) : openPanel(false);
  };
  for (const el of [$('sheetHandle'), document.querySelector('#panel header')]) {
    el.addEventListener('pointerdown', start);
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', () => { y0 = null; });
  }
})();
$('panelTab').onclick = () => openPanel(true);

window.addEventListener('aoi-selected', async e => {
  rotateNow = false;                                 // a new selection stays in view
  const sel = state.sel = e.detail, token = ++state.token;
  state.result = null;
  $('results').hidden = true;
  updateMapArea();
  if (!sel) { openPanel(false); return; }
  $('bN').value = sel.north.toFixed(4); $('bS').value = sel.south.toFixed(4);
  $('bW').value = sel.west.toFixed(4); $('bE').value = sel.east.toFixed(4);
  // Title: the country's name, or the rectangle written as latitudes and longitudes.
  const deg = (v, pos, neg) => `${+Math.abs(v).toFixed(2)}°${v < 0 ? neg : pos}`;
  $('placeName').textContent = sel.country ||
    `${deg(sel.south, 'N', 'S')} to ${deg(sel.north, 'N', 'S')}, ${deg(sel.west, 'E', 'W')} to ${deg(sel.east, 'E', 'W')}`;
  $('areaText').textContent = fmtArea(sel.areaM2) + (sel.country ? ' · inside the national border' : ' · rectangle');
  $('coordBox').open = false;
  $('areaNote').textContent = sel.country
    ? `Hotspots inside the border of ${sel.country}. The four values above are the box around it; Apply turns it into a rectangle.`
    : 'Drag the orange corner dots on the globe to resize, or type exact coordinates.';
  openPanel(true);
  setStatus('Reading hotspots…');
  await ready;
  if (token !== state.token) return;
  if (!state.rangeSet && !data.error) {               // dates not picked yet: end at the slider's month
    const ix = data.index;
    showRange(Math.floor(ix.firstMonth / 12) * 12, Math.max(ix.firstMonth, Math.min(ix.lastMonth, mapMonth())));
  }
  if (data.error) { setStatus('The hotspot data could not be loaded (' + data.error.message + ').'); return; }
  try {
    const res = await query(sel, (d, n) => { if (token === state.token) setStatus(`Reading hotspots… ${d} of ${n} map squares`); });
    if (token !== state.token) return;
    if (!res.tiles) { setStatus('No hotspots have been recorded in this area (open ocean, ice, or outside the data loaded).'); return; }
    state.result = res;
    setStatus('');
    $('results').hidden = false;
    render();
    updateMapArea();
  } catch (err) {
    if (token === state.token) setStatus('Something went wrong while reading the data: ' + err.message);
  }
});

$('bApply').onclick = () => {
  const n = +$('bN').value, s = +$('bS').value, w = +$('bW').value, ea = +$('bE').value;
  if (![n, s, w, ea].every(Number.isFinite) || n <= s || Math.abs(n) > 90 || Math.abs(s) > 90) {
    setStatus('Check the coordinates: north must be greater than south, both between −90 and 90.');
    return;
  }
  const b = enforceMin({ north: n, south: s, west: w, east: ea < w ? ea + 360 : ea });
  commit(b);
  map.fitBounds([[b.west, b.south], [b.east, b.north]], { padding: 60, maxZoom: 16 });
};

function segmented(id, key) {
  $(id).addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    state[key] = b.dataset.v;
    for (const x of $(id).children) x.classList.toggle('on', x === b);
    render();
  });
}
segmented('viewSeg', 'view');
function setUnit(u) {
  state.unit = u;
  for (const b of document.querySelectorAll('.unitSeg button')) {
    b.classList.toggle('on', b.dataset.v === u);
    b.setAttribute('aria-pressed', b.dataset.v === u);
  }
  heat.shown = '';
  showHeat();
  render();
}
for (const g of document.querySelectorAll('.unitSeg')) g.addEventListener('click', e => {
  const b = e.target.closest('button');
  if (b) setUnit(b.dataset.v);
});
// Date range: a start month + year and an end month + year.
// Until the visitor picks dates (From / To, Last 12 months, All), the range runs from January 2000
// to the month on the fire-map slider at the moment an area is selected; once they pick, their
// range stays for every later selection.
function showRange(m0, m1) {
  if (m0 > m1) [m0, m1] = [m1, m0];
  Object.assign(state, { m0, m1, y0: 2000 + Math.floor(m0 / 12), y1: 2000 + Math.floor(m1 / 12) });
  $('mo0').value = m0 % 12; $('y0').value = state.y0; $('mo1').value = m1 % 12; $('y1').value = state.y1;
}
function setRange(m0, m1) {
  state.rangeSet = true;
  showRange(m0, m1);
  render();
}
for (const id of ['mo0', 'y0', 'mo1', 'y1']) $(id).onchange = () =>
  setRange((+$('y0').value - 2000) * 12 + +$('mo0').value, (+$('y1').value - 2000) * 12 + +$('mo1').value);
ready.then(() => {
  if (data.error) return;
  const ix = data.index, fy = 2000 + Math.floor(ix.firstMonth / 12), ly = 2000 + Math.floor(ix.lastMonth / 12);
  for (const id of ['y0', 'y1']) for (let y = fy; y <= ly; y++) $(id).add(new Option(y, y));
  for (const id of ['mo0', 'mo1']) MONTHS.forEach((mn, i) => $(id).add(new Option(mn, i)));
  const all = () => setRange((fy - 2000) * 12, (ly - 2000) * 12 + 11);
  $('rangeAll').onclick = all;
  // Last 12 complete months.
  $('rangeLast12').onclick = () => { const end = ix.partialMonth === ix.lastMonth ? ix.lastMonth - 1 : ix.lastMonth; setRange(end - 11, end); };
  showRange((fy - 2000) * 12, ix.lastMonth);         // January 2000 to the latest month (see showRange)
});

// Everything shown in the panel is derived here from the monthly series.
function buildModel() {
  const ix = data.index, s = state.result[state.unit];
  const exists = m => m >= ix.firstMonth && m <= ix.lastMonth && m >= state.m0 && m <= state.m1;
  const usable = m => exists(m) && m !== ix.partialMonth;
  const years = [];
  for (let y = state.y0; y <= state.y1; y++) years.push(y);
  const med = [], p25 = [], p75 = [];
  for (let moy = 0; moy < 12; moy++) {
    const vals = years.map(y => (y - 2000) * 12 + moy).filter(usable).map(m => s[m]).sort((a, b) => a - b);
    med.push(quantile(vals, 0.5)); p25.push(quantile(vals, 0.25)); p75.push(quantile(vals, 0.75));
  }
  let max = 0, min = Infinity, total = 0;
  const rows = years.map(y => {
    let sum = 0, n = 0;
    const cells = MONTHS.map((_, moy) => {
      const m = (y - 2000) * 12 + moy;
      if (!exists(m)) return { exists: false };
      const v = s[m];
      sum += v; if (usable(m)) n++; max = Math.max(max, v); if (v > 0) min = Math.min(min, v);
      const anom = med[moy] > 0 ? (v - med[moy]) / med[moy] * 100 : null;
      return { exists: true, m, v, partial: m === ix.partialMonth, anom, score: anomScore(v, med[moy]) };
    });
    total += sum;
    return { y, cells, sum, complete: n === 12 };
  });
  let latest = null;
  for (const r of rows) for (const c of r.cells) if (c.exists && !c.partial) latest = c;
  const peakYear = rows.reduce((a, r) => (r.sum > a.sum ? r : a), rows[0]);
  const peakMoy = med.indexOf(Math.max(...med));
  // Colour position of a value: log scale stretched between the smallest and largest month,
  // so a big area with large numbers still uses the whole red-to-yellow range.
  if (!(min < max)) min = Math.min(1, max);
  const heat = v => (v <= 0 || max <= 0 ? 0 : Math.max(0, Math.log(v / min) / Math.log(max / min || 2)));
  return { ix, s, years, rows, med, p25, p75, max, min, heat, total, latest, peakYear, peakMoy };
}

function el(tag, props = {}, ...kids) {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...kids);
  return e;
}

// --- How sure are we? (margin of error) and steady heat sources (gas flares) ---
// Typical yearly error of a converted count, from the team's own validation, by the yearly count.
// VIIRS scale: Louis's model, leave-one-year-out test (median error of a cell's yearly total).
// MODIS scale: Ianis's model, accuracy table (median error of yearly totals, day + night).
const ERR = {
  vEq: [[10000, 4.1], [1000, 6.1], [0, 9.2]],
  mEq: [[10000, 4.4], [1000, 6.0], [100, 11], [10, 23], [0, 55]]
};
const errFor = (unit, n) => ERR[unit].find(([lo]) => n >= lo)[1];
function convertedPart(m) {
  const r = state.result, ix = data.index;
  if (state.unit === 'vEq') return inViirsEra(m) ? Math.max(0, r.vEq[m] - r.viirs[m]) : r.vEq[m];
  return m < ix.aquaStart || m >= ix.modisScale.viirsFrom ? r.mEq[m] : 0;
}
// Errors are added up as if they never cancel out, so the margin is on the cautious side.
function marginOfError(md) {
  let total = 0, conv = 0, err = 0;
  for (const r of md.rows) {
    let c = 0;
    for (const cell of r.cells) if (cell.exists) c += convertedPart(cell.m);
    c = Math.min(c, r.sum);
    total += r.sum; conv += c; err += c * errFor(state.unit, r.sum) / 100;
  }
  return total > 0 ? { pct: err / total * 100, convShare: conv / total * 100, rate: conv > 0 ? err / conv * 100 : 0, total } : null;
}
let staticP = null;
const loadStatic = () => (staticP ||= fetch('geo/static_sources.json').then(r => r.json()).catch(() => null));
async function staticShare(sel) {
  const st = await loadStatic();
  if (!st) return null;
  const R = regionOf(sel), c = st.cells;
  let nStatic = 0, cells = 0;
  for (let i = 0; i < c.length; i += 4) {
    const lo = (c[i] + 0.5) * 0.25 - 180, la = (c[i + 1] + 0.5) * 0.25 - 90;
    const t = { lo, la };
    const hit = R.filter(t)(0, 0) || R.filter({ lo: lo + 360, la })(0, 0);
    if (hit) { nStatic += c[i + 2]; if (c[i + 2] >= 0.5 * c[i + 3]) cells++; }
  }
  // Compare with every hotspot seen in the same years in this area (both satellites, as measured).
  const r = state.result;
  let all = 0;
  for (const y of st.years) for (let mo = 0; mo < 12; mo++) { const m = (y - 2000) * 12 + mo; all += (r.modis[m] || 0) + (r.viirs[m] || 0); }
  return { nStatic, cells, all, share: all > 0 ? Math.min(100, nStatic / all * 100) : 0, years: st.years };
}
async function renderTrust(md) {
  const box = $('trust'), token = state.token, sel = state.sel;
  box.textContent = '';
  const m = marginOfError(md);
  if (m) {
    const unitName = state.unit === 'vEq' ? 'VIIRS' : 'MODIS (Aqua)';
    const line = el('div', { className: 'tline ok' });
    if (m.convShare < 0.5) {
      line.append(el('span', { className: 'big', textContent: '±0%' }),
        el('b', { textContent: 'Margin of error. ' }),
        `Every month here is measured directly by ${unitName}; nothing is converted.`);
    } else {
      const v = m.pct < 1 ? m.pct.toFixed(1) : nf(Math.round(m.pct));
      line.append(el('span', { className: 'big', textContent: '±' + v + '%' }),
        el('b', { textContent: 'Margin of error. ' }),
        m.convShare >= 99.5 ? 'All of this total is converted from the other satellite.'
          : `${nf(Math.round(m.convShare))}% of this total is converted from the other satellite; the rest is measured directly.`);
      line.title = `The converted part is typically about ${m.rate < 10 ? m.rate.toFixed(1) : nf(Math.round(m.rate))}% off per year for an area this active (the team’s model tests).`;
    }
    box.append(line);
  }
  box.hidden = !box.childElementCount;
  const g = await staticShare(sel);
  if (!g || token !== state.token || state.sel !== sel || !box.isConnected) return;
  if (g.share >= 1 && g.nStatic >= 20) {
    box.append(el('div', { className: 'tline warn' },
      el('b', { textContent: 'Gas flares and industry in this area. ' }),
      `About ${g.share < 10 ? g.share.toFixed(1) : nf(Math.round(g.share))}% of the hotspots here (${nf(g.nStatic)} in ${g.years.join(', ')}) ` +
      'are gas flares, refineries, steel plants or volcanic lava, not fires. They are included in the counts above' +
      (g.cells ? `, and make up most hotspots in ${nf(g.cells)} map square${g.cells > 1 ? 's' : ''} of 25 km.` : '.')));
    box.hidden = false;
  }
}

function render() {
  if (!state.result) return;
  const md = state.model = buildModel(), anom = state.view === 'anom';
  const unit = UNITS[state.unit].long;

  $('modeNote').textContent = state.unit === 'vEq'
    ? 'Every month counted as VIIRS (375 m pixels) would see it. Before February 2012, when only MODIS flew, the MODIS counts (Terra and Aqua) are converted to VIIRS.'
    : 'Every month counted as MODIS on the Aqua satellite (1 km pixels) would see it. July 2002 to 2021 are Aqua’s own counts. Earlier months are converted from Terra, and months from 2022, when Aqua’s orbit drifts, from VIIRS.';

  // --- headline figures ---
  const k = $('kpis'); k.textContent = '';
  const kpi = (label, value, detail) => k.append(el('div', { className: 'kpi' },
    el('div', { className: 'k', textContent: label }), el('div', { className: 'v', textContent: value }),
    el('div', { className: 'd', textContent: detail })));
  kpi('Total, ' + rangeLabel(), nf(md.total), unit);
  kpi('Most active year', String(md.peakYear.y), nf(md.peakYear.sum) + ' hotspots');
  kpi('Peak of the fire season', MONTHS_LONG[md.peakMoy], 'median ' + nf(md.med[md.peakMoy]) + ' per ' + MONTHS[md.peakMoy]);
  if (md.latest) {
    const c = md.latest, moy = c.m % 12, y = 2000 + Math.floor(c.m / 12);
    kpi('Latest month, ' + MONTHS[moy] + ' ' + y, nf(c.v),
      c.anom === null ? 'no fires normally seen in ' + MONTHS[moy]
        : pct(c.anom) + ' against the ' + MONTHS[moy] + ' median (' + nf(md.med[moy]) + ')');
  }

  renderTrust(md);

  // --- calendar table ---
  $('calTitle').textContent = anom ? 'Difference from the monthly median' : 'Hotspots per month';
  const t = $('cal'); t.textContent = '';
  const head = el('tr', {}, el('th', { className: 'y', textContent: 'Year', scope: 'col' }));
  MONTHS.forEach(mn => head.append(el('th', { textContent: mn, scope: 'col' })));
  head.append(el('th', { className: 'tot', textContent: 'Total', scope: 'col' }));
  t.append(el('thead', {}, head));
  const body = el('tbody');
  for (const r of [...md.rows].reverse()) {
    const tr = el('tr', {}, el('td', { className: 'y', textContent: r.y }));
    r.cells.forEach((c, moy) => {
      if (!c.exists) { tr.append(el('td', { className: 'na', textContent: '–' })); return; }
      const td = el('td', { className: 'c' + (c.partial ? ' partial' : '') + (c.m === mapMonth() ? ' now' : '') });
      td.dataset.m = c.m;
      let bright;
      if (anom) {
        td.style.background = divColor(c.score); bright = false;
        td.textContent = c.anom === null ? (c.v > 0 ? 'new' : '0') : pct(Math.max(-999, Math.min(999, c.anom)));
        td.style.fontSize = '10px';
      } else {
        const tt = md.heat(c.v);
        const col = seqColor(tt);
        if (c.v > 0) td.style.background = col;
        bright = c.v > 0 && textOn(col) === '#0b0b0b';
        td.textContent = compact(c.v);
      }
      td.style.color = bright ? '#0b0b0b' : '#f0efec';
      td.dataset.tip = `${MONTHS_LONG[moy]} ${r.y}: ${nf(c.v)} ${unit}\nMedian for ${MONTHS[moy]}: ${nf(md.med[moy])}` +
        (c.anom === null ? '' : `\nDifference: ${pct(c.anom)}`) + (c.partial ? '\nIncomplete month' : '') + '\nClick to show this month on the map';
      tr.append(td);
    });
    tr.append(el('td', { className: 'tot', textContent: compact(r.sum), title: nf(r.sum) }));
    body.append(tr);
  }
  const medRow = el('tr', { className: 'med' }, el('td', { className: 'y', textContent: 'Median' }));
  md.med.forEach(v => medRow.append(el('td', { textContent: compact(v), title: nf(v) })));
  medRow.append(el('td', { className: 'tot', textContent: compact(md.med.reduce((a, b) => a + b, 0)) }));
  body.append(medRow);
  t.append(body);

  const ramp = $('ramp'); ramp.textContent = '';
  const bar = el('i');
  if (anom) {
    bar.style.background = 'linear-gradient(90deg,#3987e5,#383835,#e66767)';
    ramp.append('¼ of normal or less', bar, '4× normal or more');
  } else {
    bar.style.background = `linear-gradient(90deg,${SEQ.join(',')})`;
    ramp.append(compact(md.min), bar, compact(md.max) + ' (log scale)');
  }
  $('calNote').textContent = (anom ? 'Each month is compared with the median of the same month over ' + rangeLabel() + '. ' : '') +
    (md.ix.partialMonth >= 0 ? 'The outlined month is incomplete and is left out of the medians. ' : '') +
    '“–” means outside the chosen dates or no satellite data (the record runs from ' + md.ix.firstDate.slice(0, 7) + ' to ' + md.ix.lastDate.slice(0, 7) + ').';

  updateMapArea();
  drawSeason(md, unit);
  drawAnomaly(md, unit);
  drawMonthly(md);

  const rawPts = md.rows.reduce((a, r) => a + r.cells.reduce((x, c) => x + (c.exists ? state.result.modis[c.m] + state.result.viirs[c.m] : 0), 0), 0);
  state.rawPoints = rawPts;
  // The button stays clickable even when the search is too big, so it never looks broken:
  // clicking it then explains the limit and offers a smaller date range.
  $('dlPoints').disabled = rawPts === 0;
  const mb = Math.max(1, Math.round(rawPts * 75 / 1e6));
  $('dlNote').textContent = rawPts > MAX_POINTS
    ? `This search holds ${nf(rawPts)} hotspots, too many for one file (the limit is ${nf(MAX_POINTS)}).`
    : `The hotspot file will contain ${nf(rawPts)} rows, about ${mb} MB (every MODIS and VIIRS detection in the area and dates chosen).`;
  $('sourceNote').textContent = `Source: NASA FIRMS archive (MODIS Collection 6.1, VIIRS S-NPP 375 m), ${md.ix.coverage}, ` +
    `${md.ix.firstDate} to ${md.ix.lastDate}. MODIS and VIIRS are converted into each other by the team’s two models, fitted on the years both sensors flew (from 2012).` +
    ((md.ix.gapDays || []).length ? ` VIIRS outage days (${md.ix.gapDays.length}, e.g. ${md.ix.gapDays.slice(-3).join(', ')}) are filled with converted MODIS.` : '');
}

/* ================= 6. Charts (plain SVG) ================= */
const NS = 'http://www.w3.org/2000/svg';
const FONT = '"IBM Plex Sans", system-ui, sans-serif';
function svgEl(tag, attrs = {}, text) {
  const e = document.createElementNS(NS, tag);
  for (const [k2, v] of Object.entries(attrs)) e.setAttribute(k2, v);
  if (text !== undefined) e.textContent = text;
  return e;
}
// Axis top: the next round value above the data, and how many gridline steps suit it.
const NICE = [[1, 5], [1.2, 4], [1.5, 3], [2, 4], [2.5, 5], [3, 3], [4, 4], [5, 5], [6, 3], [8, 4], [10, 5]];
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
  return NICE.find(([m]) => n <= m + 1e-9)[0] * p;
}
function axes(svg, W, H, pad, top) {
  svg.textContent = '';
  svg.append(svgEl('rect', { width: W, height: H, fill: '#1a1a19' }));
  const y = v => H - pad.b - (v / top) * (H - pad.t - pad.b);
  const lead = top / Math.pow(10, Math.floor(Math.log10(top))), div = (NICE.find(([m]) => Math.abs(m - lead) < 1e-6) || [0, 4])[1];
  for (let i = 0; i <= div; i++) {
    const v = top * i / div;
    svg.append(svgEl('line', { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: i ? '#2c2c2a' : '#383835', 'stroke-width': 1 }));
    svg.append(svgEl('text', { x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end', fill: '#898781', 'font-size': 11, 'font-family': FONT }, compact(v)));
  }
  return y;
}

// Critical period: the shortest run of consecutive months (it may run over New Year) that
// holds at least 80% of a typical year's hotspots. Returns null when fires are spread out.
function criticalPeriod(med) {
  const total = med.reduce((a, b) => a + b, 0);
  if (total <= 0) return null;
  for (let len = 1; len <= 9; len++) {
    let best = null;
    for (let start = 0; start < 12; start++) {
      let sum = 0;
      for (let k = 0; k < len; k++) sum += med[(start + k) % 12];
      if (sum >= 0.8 * total && (!best || sum > best.sum)) best = { start, len, sum };
    }
    if (best) return { ...best, share: best.sum / total, months: Array.from({ length: len }, (_, k) => (best.start + k) % 12) };
  }
  return null;
}

function drawSeason(md, unit) {
  const svg = $('seasonChart'), W = 560, H = 220, pad = { l: 44, r: 46, t: 30, b: 26 };
  // Compare the typical year with the year picked in the title (default: the newest year in the
  // range that has any data).
  const years = md.rows.filter(r => r.cells.some(c => c.exists)).reverse();
  const row = years.find(r => r.y === state.seasonYear) || years[0] || md.rows[0];
  const pick = $('seasonYear');
  pick.textContent = '';
  for (const r of years.length ? years : [row]) pick.add(new Option(r.y, r.y));
  pick.value = row.y;
  pick.onchange = () => { state.seasonYear = +pick.value; drawSeason(md, unit); };
  const yr = row.cells.map(c => (c.exists && !c.partial ? c.v : null));
  const top = niceMax(Math.max(...md.p75, ...yr.map(v => v || 0), 1));
  const y = axes(svg, W, H, pad, top);
  const step = (W - pad.l - pad.r) / 11, x = i => pad.l + i * step;
  // Shade the critical period behind the lines, with an orange bracket and its name on top.
  const cp = criticalPeriod(md.med);
  if (cp) {
    const name = cp.len === 1 ? MONTHS[cp.start] : `${MONTHS[cp.start]}–${MONTHS[(cp.start + cp.len - 1) % 12]}`;
    const runs = [];                                   // one run, or two when it wraps over New Year
    for (const m of cp.months) { const last = runs[runs.length - 1]; if (last && m === last[1] + 1) last[1] = m; else runs.push([m, m]); }
    for (const [a, b] of runs) {
      const x0 = Math.max(pad.l, x(a) - step / 2), x1 = Math.min(W - pad.r, x(b) + step / 2);
      svg.append(svgEl('rect', { x: x0, y: pad.t, width: x1 - x0, height: H - pad.t - pad.b, fill: '#f0efec', 'fill-opacity': 0.05 }));
      svg.append(svgEl('rect', { x: x0, y: pad.t - 8, width: x1 - x0, height: 3, rx: 1.5, fill: C_MED }));
    }
    const mid = runs.length === 1 ? (Math.max(pad.l, x(runs[0][0]) - step / 2) + Math.min(W - pad.r, x(runs[0][1]) + step / 2)) / 2 : x(runs[runs.length - 1][0]);
    label(svg, Math.max(pad.l + 90, Math.min(W - pad.r - 90, mid)), pad.t - 14, `Critical period: ${name} · ${Math.round(cp.share * 100)}% of fires`, 'middle', '#f0efec', 11);
    $('seasonNote').textContent = `In a typical year, ${Math.round(cp.share * 100)}% of this area's hotspots fall in ${name}` +
      ` (the shortest run of months holding at least 80%). Peak month: ${MONTHS_LONG[md.peakMoy]}.`;
  } else {
    $('seasonNote').textContent = 'No clear fire season: hotspots are spread over most of the year.';
  }
  const lg = $('seasonLegend'); lg.textContent = '';
  for (const [cls, c, label] of [['', C_MED, 'Typical year (median)'], ['band', C_BAND, 'Usual range (middle half of years)'], ['', C_NOW, String(row.y)]]) {
    const sp = el('span', { className: cls, textContent: label }); sp.style.setProperty('--c', c); lg.append(sp);
  }
  const band = md.p75.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join('') +
    md.p25.map((v, i) => `L${x(11 - i)},${y(md.p25[11 - i])}`).join('') + 'Z';
  svg.append(svgEl('path', { d: band, fill: C_BAND }));
  const line = (vals, color) => {
    let d = '', pen = false;
    vals.forEach((v, i) => { if (v === null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${x(i)},${y(v)}`; pen = true; });
    svg.append(svgEl('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  };
  line(md.med, C_MED);
  line(yr, C_NOW);
  yr.forEach((v, i) => { if (v !== null) svg.append(svgEl('circle', { cx: x(i), cy: y(v), r: 4, fill: C_NOW, stroke: '#1a1a19', 'stroke-width': 2 })); });
  // Direct labels at the right end of each line.
  const lastI = yr.reduce((a, v, i) => (v !== null ? i : a), -1);
  let yMed = y(md.med[11]) + 4, yYr = lastI >= 0 ? y(yr[lastI]) + 4 : -99;
  if (lastI === 11 && Math.abs(yMed - yYr) < 13) { yYr < yMed ? (yMed = yYr + 13) : (yYr = yMed + 13); }
  svg.append(svgEl('text', { x: x(11) + 8, y: yMed, fill: '#c3c2b7', 'font-size': 11, 'font-family': FONT }, 'Median'));
  if (lastI >= 0) svg.append(svgEl('text', { x: x(lastI) + 8, y: yYr, fill: '#c3c2b7', 'font-size': 11, 'font-family': FONT }, row.y));
  MONTHS.forEach((mn, i) => {
    svg.append(svgEl('text', { x: x(i), y: H - 8, 'text-anchor': 'middle', fill: '#898781', 'font-size': 11, 'font-family': FONT }, mn));
    const g = svgEl('g', { class: 'hit' });
    g.dataset.tip = `${MONTHS_LONG[i]}\nMedian: ${nf(md.med[i])}\nMiddle half of years: ${nf(md.p25[i])} – ${nf(md.p75[i])}\n` +
      `${row.y}: ${yr[i] === null ? 'no data' : nf(yr[i])}`;
    g.append(svgEl('line', { class: 'cross', x1: x(i), x2: x(i), y1: pad.t, y2: H - pad.b, stroke: '#898781', 'stroke-width': 1, opacity: 0 }));
    g.append(svgEl('rect', { x: x(i) - step / 2, y: pad.t, width: step, height: H - pad.t - pad.b, fill: 'transparent' }));
    svg.append(g);
  });
  svg.setAttribute('aria-label', `Hotspots by month of the year (${unit}): median, middle half of years, and ${row.y}`);
}

const C_HARM = '#e8471a', C_NAIVE = '#898781', C_MED = '#f37a22', C_NOW = '#fdd23f', C_BAND = '#4a4944', C_BAND_WIDE = '#302f2c';
const label = (svg, x, y, t, anchor = 'middle', color = '#898781', size = 11) =>
  svg.append(svgEl('text', { x, y, 'text-anchor': anchor, fill: color, 'font-size': size, 'font-family': FONT }, t));
const legend = (id, items) => {
  const lg = $(id); lg.textContent = '';
  for (const [c, t] of items) { const sp = el('span', { textContent: t }); sp.style.setProperty('--c', c); lg.append(sp); }
};

// Yearly anomaly: how far each year is above or below the average of the complete years in
// the range. An unfinished year is compared with the same months of the other years.
const C_ABOVE = '#e8471a', C_BELOW = '#5b8bd0';
function drawAnomaly(md, unit) {
  const svg = $('anomChart'), W = 560, H = 220, pad = { l: 48, r: 10, t: 16, b: 26 };
  const ok = c => c.exists && !c.partial;
  const full = md.rows.filter(r => r.cells.every(ok));
  legend('anomLegend', [[C_ABOVE, 'Above average'], [C_BELOW, 'Below average']]);
  svg.textContent = '';
  if (full.length < 3) { $('anomNote').textContent = 'Needs at least three complete years in the selected range.'; return; }
  const avgFull = full.reduce((a, r) => a + r.sum, 0) / full.length;
  const bars = md.rows.map(r => {
    const have = r.cells.map(ok);
    if (!have.some(Boolean)) return null;
    const complete = have.every(Boolean);
    const part = row => row.cells.reduce((a, c, i) => a + (have[i] && ok(c) ? c.v : 0), 0);
    const value = part(r), base = complete ? avgFull : full.reduce((a, f) => a + part(f), 0) / full.length;
    const first = have.indexOf(true), last = have.lastIndexOf(true);
    return { y: r.y, value, base, complete, span: complete ? '' : `${MONTHS[first]}–${MONTHS[last]}`, a: base > 0 ? (value - base) / base * 100 : 0 };
  }).filter(Boolean);
  const lim = Math.max(25, ...bars.map(b => Math.abs(b.a)));
  const step0 = lim > 200 ? 100 : lim > 100 ? 50 : 25, top = Math.ceil(lim / step0) * step0;
  const y = v => pad.t + (1 - (v + top) / (2 * top)) * (H - pad.t - pad.b);
  svg.append(svgEl('rect', { width: W, height: H, fill: '#1a1a19' }));
  for (let v = -top; v <= top; v += step0) {
    svg.append(svgEl('line', { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: v === 0 ? '#898781' : '#2c2c2a' }));
    label(svg, pad.l - 6, y(v) + 4, (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v) + '%', 'end');
  }
  const n = bars.length, slot = (W - pad.l - pad.r) / n, bw = Math.max(3, Math.min(22, slot - 3));
  const every = n > 18 ? 5 : n > 9 ? 2 : 1;
  // Label the three most unusual years, skipping a year right next to one already labelled.
  const top3 = [];
  for (const b of [...bars].sort((p, q) => Math.abs(q.a) - Math.abs(p.a))) {
    if (top3.length === 3) break;
    if (!top3.some(t => Math.abs(t.y - b.y) <= 1)) top3.push(b);
  }
  bars.forEach((b, i) => {
    const cx = pad.l + slot * (i + 0.5), y0 = y(0), y1 = y(Math.max(-top, Math.min(top, b.a))), up = b.a >= 0;
    const h = Math.abs(y1 - y0), rr = Math.min(3, bw / 2, h);
    const tY = up ? y1 : y1, x0 = cx - bw / 2;
    // Rounded at the far end, flat on the zero line.
    const d = up
      ? `M${x0},${y0}V${tY + rr}Q${x0},${tY} ${x0 + rr},${tY}H${x0 + bw - rr}Q${x0 + bw},${tY} ${x0 + bw},${tY + rr}V${y0}Z`
      : `M${x0},${y0}V${tY - rr}Q${x0},${tY} ${x0 + rr},${tY}H${x0 + bw - rr}Q${x0 + bw},${tY} ${x0 + bw},${tY - rr}V${y0}Z`;
    const p = svgEl('path', { class: 'bar', d, fill: up ? C_ABOVE : C_BELOW, 'fill-opacity': b.complete ? 1 : 0.45 });
    p.dataset.tip = `${b.y}${b.complete ? '' : ` (${b.span} only)`}: ${pct(b.a)} against the average\n` +
      `${nf(b.value)} against an average of ${nf(b.base)} ${unit}`;
    svg.append(p);
    if (top3.includes(b) && Math.abs(b.a) >= 5) label(svg, cx, up ? y1 - 5 : y1 + 13, pct(b.a), 'middle', '#c3c2b7', 10);
    if (b.y % every === 0 || n <= 9) label(svg, cx, H - 8, b.y);
  });
  const hi = [...bars].filter(b => b.complete && b.a > 0).sort((p, q) => q.a - p.a).slice(0, 3).map(b => b.y), part = bars.find(b => !b.complete && b.y === bars[bars.length - 1].y);
  $('anomNote').textContent = `Each year against the average of ${full.length} complete years (${nf(avgFull)} ${unit} a year).` +
    (hi.length ? ` Most unusual high years: ${hi.join(', ')}.` : '') +
    (part ? ` ${part.y} (paler) is not finished: it is compared with ${part.span} of the other years.` : '');
}

// The whole record month by month, in the chosen units.
function drawMonthly(md) {
  const svg = $('monthlyChart'), W = 560, H = 220, pad = { l: 44, r: 10, t: 16, b: 26 }, s = md.s, ix = md.ix, vu = state.unit === 'vEq';
  const months = [];
  for (const row of md.rows) for (const c of row.cells) if (c.exists && !c.partial) months.push(c.m);
  legend('monthlyLegend', [[`linear-gradient(90deg,${SEQ.slice(2).join(',')})`, 'Hotspots per month (colour = how many)']]);
  if (!months.length) { svg.textContent = ''; return; }
  const top = niceMax(Math.max(...months.map(m => s[m]), 1));
  const y = axes(svg, W, H, pad, top);
  const m0 = months[0], m1 = months[months.length - 1], x = m => pad.l + (m1 > m0 ? (m - m0) / (m1 - m0) : 0.5) * (W - pad.l - pad.r);
  if (ix.viirsStart > m0 && ix.viirsStart <= m1) {
    svg.append(svgEl('line', { x1: x(ix.viirsStart), x2: x(ix.viirsStart), y1: pad.t - 6, y2: H - pad.b, stroke: '#898781', 'stroke-dasharray': '3 3' }));
    label(svg, x(ix.viirsStart) + 4, pad.t + 2, vu ? 'VIIRS data from here' : 'converted from VIIRS from here', 'start', '#898781', 10);
  }
  const path = (get, color, w, opacity = 1) => {
    let d = '', prev = -2;
    for (const m of months) { const v = get(m); if (v === null) { prev = -2; continue; } d += `${m === prev + 1 ? 'L' : 'M'}${x(m).toFixed(1)},${y(v).toFixed(1)}`; prev = m; }
    svg.append(svgEl('path', { d, fill: 'none', stroke: color, 'stroke-width': w, 'stroke-linejoin': 'round', 'stroke-opacity': opacity }));
  };
  const grad = svgEl('linearGradient', { id: 'fireGrad', gradientUnits: 'userSpaceOnUse', x1: 0, x2: 0, y1: H - pad.b, y2: pad.t });
  SEQ.slice(2).forEach((c, i, a) => grad.append(svgEl('stop', { offset: i / (a.length - 1), 'stop-color': c })));
  const defs = svgEl('defs'); defs.append(grad); svg.append(defs);
  path(m => s[m], 'url(#fireGrad)', 1.6);
  const y0 = 2000 + Math.floor(m0 / 12), y1 = 2000 + Math.floor(m1 / 12), every = y1 - y0 > 18 ? 5 : y1 - y0 > 8 ? 2 : 1;
  for (let yr = y0; yr <= y1; yr++) if (yr % every === 0 || y1 - y0 < 3) {
    const m = (yr - 2000) * 12;
    if (m >= m0 && m <= m1) { svg.append(svgEl('line', { x1: x(m), x2: x(m), y1: H - pad.b, y2: H - pad.b + 4, stroke: '#383835' })); label(svg, x(m), H - 8, yr); }
  }
  const step = (W - pad.l - pad.r) / Math.max(1, m1 - m0);
  for (const m of months) {
    const g = svgEl('g', { class: 'hit' });
    g.dataset.tip = `${MONTHS_LONG[m % 12]} ${2000 + Math.floor(m / 12)}\n${nf(s[m])} ${UNITS[state.unit].long}`;
    g.addEventListener('click', () => showMonthOnMap(m));
    g.append(svgEl('line', { class: 'cross', x1: x(m), x2: x(m), y1: pad.t, y2: H - pad.b, stroke: '#898781', opacity: 0 }));
    g.append(svgEl('rect', { x: x(m) - step / 2, y: pad.t, width: step, height: H - pad.t - pad.b, fill: 'transparent' }));
    svg.append(g);
  }
  $('monthlyNote').textContent = 'Every month of the selected years in one line, to spot the biggest fire months and long-term changes. ' + (vu
    ? 'From February 2012 the counts come from VIIRS; before that, MODIS converted to VIIRS.'
    : 'Until February 2012 the counts come from MODIS; after that, VIIRS converted to MODIS.');
}

// One shared tooltip for table cells and chart marks.
const tip = $('tip');
document.addEventListener('mousemove', e => {
  const t = e.target.closest && e.target.closest('[data-tip]');
  if (!t) { tip.style.display = 'none'; return; }
  tip.textContent = t.dataset.tip;
  tip.style.display = 'block';
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(innerWidth - r.width - 8, e.clientX - r.width - 14)) + 'px';
  tip.style.top = Math.max(8, Math.min(innerHeight - r.height - 8, e.clientY + 14)) + 'px';
});

/* ================= 7. Downloads ================= */
// Saving files. Where the browser offers it (Chrome, Edge, the Claude app), a "Save as"
// window opens first, while the click still counts as the user's action, and the file is
// then written straight to disk piece by piece. Otherwise (Safari, Firefox) the classic
// download link is used. produce(write) calls write(text or Blob) as many times as needed.
const MAX_POINTS = 3000000;
// CSV in the standard international (English) format: ',' between columns, '.' in decimals.
// The file starts with a byte-order mark so Excel reads it as UTF-8.
const CSV = { sep: ',', num: v => String(v), bom: '\uFEFF' };
const csvLine = cells => cells.join(CSV.sep);
const fileTypes = { csv: ['CSV file', 'text/csv'], png: ['PNG image', 'image/png'] };
// A table is written as CSV through three calls: begin(columns), rows(list), end().
function tableSink(write) {
  const pending = [];
  return {
    begin: cols => pending.push(write(CSV.bom + csvLine(cols) + '\r\n')),
    rows: rows => { if (rows.length) pending.push(write(rows.map(r => csvLine(r.map(v => (v && v.date ? v.date : v)))).join('\r\n') + '\r\n')); },
    end: () => Promise.all(pending)
  };
}
// Browsers built into other apps (such as the Claude app's preview pane) cannot save files.
const EMBEDDED = /\bClaude\//.test(navigator.userAgent);
async function saveFile(name, produce) {
  const ext = name.split('.').pop(), [desc, mime] = fileTypes[ext];
  if (window.showSaveFilePicker) {
    let handle = null;
    const asked = performance.now();
    try {
      handle = await window.showSaveFilePicker({ suggestedName: name, types: [{ description: desc, accept: { [mime]: ['.' + ext] } }] });
    } catch (e) {
      // A real Cancel takes a person at least a moment; an instant refusal means this browser
      // does not offer the window, so fall back to the classic download below.
      if (e.name === 'AbortError' && performance.now() - asked > 400) return false;
    }
    if (handle) {
      const out = await handle.createWritable();
      try { await produce(part => out.write(part)); await out.close(); }
      catch (e) { await out.abort(); throw e; }
      return true;
    }
  }
  const parts = [], started = performance.now();
  await produce(part => { parts.push(part); });
  const blob = new Blob(parts, { type: mime }), url = URL.createObjectURL(blob);
  // Safari and Firefox only start a download within about a second of the click. A file that
  // took longer to prepare (a big hotspot search) gets a "Save" link for a second click instead.
  if (performance.now() - started < 800) {
    const a = el('a', { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return 'saved';
  }
  const note = $('dlNote'), mb = blob.size / 1e6;
  const link = el('a', { href: url, download: name, className: 'savelink',
    textContent: `Save ${name} (${mb < 1 ? Math.max(1, Math.round(blob.size / 1e3)) + ' KB' : mb.toFixed(1) + ' MB'})` });
  link.addEventListener('click', () => setTimeout(() => { note.textContent = `Saved ${name}.`; URL.revokeObjectURL(url); }, 1000));
  note.textContent = 'Your file is ready: ';
  note.append(link);
  return 'ready';
}
// Run a download button: show progress, report failures instead of failing silently.
async function runDownload(btn, name, produce) {
  if (EMBEDDED) {
    $('dlNote').textContent = `This built-in browser cannot save files. Open ${location.origin} in Chrome, Safari or Firefox to download.`;
    return;
  }
  const label = btn.textContent;
  btn.disabled = true;
  try {
    const saved = await saveFile(name, produce);
    if (saved === true || saved === 'saved') $('dlNote').textContent = `Saved ${name}.`;
  } catch (e) {
    $('dlNote').textContent = `Could not save ${name}: ${e.message}`;
  } finally {
    btn.textContent = label;
    btn.disabled = btn === $('dlPoints') && !state.rawPoints;
  }
}
const fileStem = () => {
  const s = state.sel, f = v => v.toFixed(3);
  const where = s.country ? s.country.replace(/[^A-Za-z0-9]+/g, '_') : `${f(s.south)}_${f(s.west)}_${f(s.north)}_${f(s.east)}`;
  const ym = m => `${2000 + Math.floor(m / 12)}-${String(m % 12 + 1).padStart(2, '0')}`;
  return `fire_${where}_${fullYears() ? `${state.y0}-${state.y1}` : `${ym(state.m0)}_to_${ym(state.m1)}`}`;
};

$('dlTable').onclick = () => runDownload($('dlTable'), `${fileStem()}_monthly.csv`, async write => {
  const r = state.result, md = state.model, ix = data.index;
  const out = tableSink(write);
  out.begin(['year', 'month', 'modis_original', 'viirs_original', 'viirs_equivalent', 'modis_aqua_equivalent', 'viirs_equivalent_source', 'modis_aqua_equivalent_source', 'complete_month']);
  const rows = [];
  for (const row of md.rows) for (const c of row.cells) if (c.exists) {
    rows.push([row.y, c.m % 12 + 1, r.modis[c.m], r.viirs[c.m], +r.vEq[c.m].toFixed(1), +r.mEq[c.m].toFixed(1),
      inViirsEra(c.m) ? (data.gapIdx[c.m] >= 0 ? 'VIIRS + MODIS converted on VIIRS outage days' : 'VIIRS') : 'MODIS converted to VIIRS',
      c.m < ix.aquaStart ? 'Terra converted to Aqua' : c.m < ix.modisScale.viirsFrom ? 'Aqua' : 'VIIRS converted to Aqua', c.partial ? 'no' : 'yes']);
  }
  out.rows(rows);
  await out.end();
});

// Too many hotspots: explain, and offer the largest recent date range that fits.
function tooManyPoints() {
  const r = state.result, note = $('dlNote'), last = Math.min(state.m1, data.index.lastMonth);
  const pts = m => (r.modis[m] || 0) + (r.viirs[m] || 0);
  let m0 = last, n = 0;
  while (m0 >= state.m0 && n + pts(m0) <= MAX_POINTS) { n += pts(m0); m0--; }
  m0++;
  note.textContent = `This search holds ${nf(state.rawPoints)} hotspots, more than the ${nf(MAX_POINTS)} a browser can put in one file. ` +
    'Choose a smaller area or a shorter date range. ';
  if (m0 <= last) {
    const b = el('a', { href: '#', className: 'savelink', textContent: `Use ${monthName(m0)} – ${monthName(last)} (${nf(n)} hotspots)` });
    b.onclick = e => { e.preventDefault(); setRange(m0, last); };
    note.append(b);
  }
}
$('dlPoints').onclick = () => state.rawPoints > MAX_POINTS ? tooManyPoints() : runDownload($('dlPoints'), `${fileStem()}_hotspots.csv`, async write => {
  const btn = $('dlPoints'), ix = data.index;
  {
    const m0 = state.m0, m1 = state.m1;
    const SAT = ['Terra', 'Aqua', 'Suomi NPP'], CONF = ['low', 'nominal', 'high'];
    const out = tableSink(write);
    out.begin(['latitude', 'longitude', 'acq_date', 'satellite', 'instrument', 'confidence', 'frp', 'daynight', 'type', 'viirs_equivalent_weight', 'modis_aqua_equivalent_weight']);
    await walk(state.sel, true, {
      points(t, dv, n, keep) {
        const rows = [];
        for (let i = 0, o = 0; i < n; i++, o += REC) {
          const la = dv.getUint16(o, true), lo = dv.getUint16(o + 2, true);
          if (keep && !keep(la, lo)) continue;
          const day = dv.getUint16(o + 4, true), m = data.dayMonth[day];
          if (m < m0 || m > m1) continue;
          const fl = dv.getUint8(o + 8), sat = fl & 3, viirs = sat === 2, w = pointWeights(t, la, lo, day, m, fl);
          // Weights = what this detection counts for on each scale.
          const weight = +w.v.toFixed(4), weightM = +w.m.toFixed(4);
          rows.push([+(t.la + la / 65535).toFixed(5), +(t.lo + lo / 65535).toFixed(5),
            { date: new Date(Date.UTC(2000, 0, 1 + day)).toISOString().slice(0, 10) },
            SAT[sat], viirs ? 'VIIRS' : 'MODIS', CONF[fl >> 5 & 3], dv.getUint16(o + 6, true) / 10, fl & 4 ? 'N' : 'D', fl >> 3 & 3, weight, weightM]);
        }
        out.rows(rows);
      }
    }, (d, n) => { btn.textContent = `Preparing… ${Math.round(d / n * 100)}%`; });
    btn.textContent = 'Saving…';
    await out.end();
  }
});

$('dlPng').onclick = () => runDownload($('dlPng'), fileStem() + (state.view === 'anom' ? '_anomaly' : '_calendar') + '.png', async write => {
  const md = state.model, sel = state.sel, S = 2, W = 1200, rowH = 24, x0 = 70, cw = 78;
  const calH = (md.rows.length + 2) * rowH, chartH = 780;
  const cv = el('canvas', { width: W * S, height: (120 + calH + chartH) * S }), c = cv.getContext('2d');
  c.scale(S, S);
  c.fillStyle = '#12151c'; c.fillRect(0, 0, W, cv.height / S);
  const text = (s, x, y, color = '#f0efec', size = 13, align = 'left', weight = 400) => {
    c.fillStyle = color; c.font = `${weight} ${size}px ${FONT}`; c.textAlign = align; c.fillText(s, x, y);
  };
  const anom = state.view === 'anom';
  text((anom ? 'Fire activity anomaly' : 'Burning activity calendar') + ` (${UNITS[state.unit].long}, ${UNITS[state.unit].px} pixels)`, 24, 38, '#f0efec', 22, 'left', 600);
  text(`Area: ${sel.country ? sel.country + ' · ' : ''}${sel.south.toFixed(4)}° to ${sel.north.toFixed(4)}° lat, ${sel.west.toFixed(4)}° to ${sel.east.toFixed(4)}° lon · ${fmtArea(sel.areaM2)} · ${rangeLabel()}`, 24, 62, '#c3c2b7');
  text($('sourceNote').textContent, 24, 82, '#898781', 11);
  let y = 110;
  MONTHS.forEach((mn, i) => text(mn, x0 + cw * (i + 0.5), y, '#898781', 12, 'center'));
  text('Total', W - 30, y, '#898781', 12, 'right');
  for (const r of [...md.rows].reverse()) {
    y += rowH;
    text(String(r.y), 24, y, '#c3c2b7', 12);
    r.cells.forEach((cell, i) => {
      if (!cell.exists) { text('–', x0 + cw * (i + 0.5), y, '#383835', 12, 'center'); return; }
      const tt = md.heat(cell.v);
      if (anom || cell.v > 0) { c.fillStyle = anom ? divColor(cell.score) : seqColor(tt); c.fillRect(x0 + cw * i + 1, y - 16, cw - 2, rowH - 2); }
      const label = anom ? (cell.anom === null ? (cell.v > 0 ? 'new' : '0') : pct(cell.anom)) : nf(cell.v);
      text(label, x0 + cw * (i + 0.5), y, !anom && cell.v > 0 ? textOn(seqColor(tt)) : '#f0efec', 12, 'center');
    });
    text(nf(r.sum), W - 30, y, '#f0efec', 12, 'right', 600);
  }
  y += rowH;
  text('Median', 24, y, '#898781', 12);
  md.med.forEach((v, i) => text(nf(v), x0 + cw * (i + 0.5), y, '#c3c2b7', 12, 'center'));
  y += 30;
  const drawSvg = (id, dx, dy, w, h) => new Promise((res, rej) => {
    const s = $(id).cloneNode(true);
    s.setAttribute('xmlns', NS); s.setAttribute('width', w); s.setAttribute('height', h);
    const img = new Image();
    img.onload = () => { c.drawImage(img, dx, dy, w, h); res(); };
    img.onerror = rej;
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(s));
  });
  text('Fire season: typical year (orange), usual range (grey), ' + $('seasonYear').value + ' (yellow)', 24, y + 14, '#c3c2b7', 13);
  text('Unusual years: difference from the average', 616, y + 14, '#c3c2b7', 13);
  await drawSvg('seasonChart', 24, y + 26, 560, 220);
  await drawSvg('anomChart', 616, y + 26, 560, 220);
  text('Monthly record (colour = number of hotspots)', 24, y + 280, '#c3c2b7', 13);
  await drawSvg('monthlyChart', 24, y + 292, 1152, 452);
  await write(await new Promise(res => cv.toBlob(res, 'image/png')));
});

/* ----- Precompute country totals (run on this computer only) -----
   Open http://localhost:8765/?precompute after every data rebuild: every country is counted
   once with the exact border method and the result is saved as data/countries.bin through
   tools/serve.py. Then publish with tools/deploy.sh. */
async function precomputeCountries() {
  await ready;
  if (data.error) return;
  precomputing = true;
  const list = await loadCountries(), M = data.index.months;
  const buf = new ArrayBuffer(16 + list.length * 4 * M * 4), dv = new DataView(buf);
  dv.setUint32(0, list.length, true); dv.setUint32(4, M, true); dv.setFloat64(8, data.index.hotspots, true);
  const t0 = performance.now();
  for (const c of list) {
    if (c.area === undefined) c.area = countryArea(c);
    $('heatCaption').textContent = `Counting countries… ${c.i + 1}/${list.length}: ${c.n}`;
    const r = await query({ west: c.b[0], south: c.b[1], east: c.b[2], north: c.b[3], areaM2: c.area, country: c.n, poly: c });
    const f = new Float32Array(buf, 16 + c.i * 4 * M * 4, 4 * M);
    f.set(r.modis, 0); f.set(r.viirs, M); f.set(r.vEq, 2 * M); f.set(r.mEq, 3 * M);
  }
  const res = await fetch('data/countries.bin', { method: 'PUT', body: buf });
  precomputing = false;
  countryTotalsP = null;
  $('heatCaption').textContent = res.ok
    ? `Saved data/countries.bin: ${list.length} countries in ${Math.round((performance.now() - t0) / 1000)} s.`
    : `Could not save data/countries.bin (HTTP ${res.status}). Is the page served by tools/serve.py?`;
  window.precomputeResult = res.ok;
}
if (/[?&]precompute\b/.test(location.search) && /^(localhost|127\.0\.0\.1)$/.test(location.hostname)) precomputeCountries();
