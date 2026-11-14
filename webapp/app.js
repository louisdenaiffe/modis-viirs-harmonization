'use strict';
/* Fire Globe: globe + area selection + harmonized burning-activity calendar.
   Sections: 1 starfield, 2 globe, 3 selection, 4 data, 5 panel, 6 charts, 7 downloads. */

const EARTH_R = 6371008.8;              // mean Earth radius, metres
const MIN_SIDE_M = 375;                 // one VIIRS pixel: smallest allowed selection side
const DEG = Math.PI / 180;
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
        attribution: 'Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community · Hotspots: NASA FIRMS'
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
      { id: 'aoi-fill', type: 'fill', source: 'aoi', paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.1 } },
      { id: 'aoi-line', type: 'line', source: 'aoi', paint: { 'line-color': '#ffffff', 'line-width': 2.5 } }
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
function drawBox(b) {
  map.getSource('aoi').setData({ type: 'FeatureCollection', features: b ? [rectPolygon(b)] : [] });
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
    redrawSelection();
    mapEl.classList.toggle('selecting', selectMode);
    if (!selectMode) lockPan(false);
    // Shift + click without dragging: select the country under the cursor.
    if (!cancel && d.shift) selectCountryAt(d.start);
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
const loadCountries = () => countriesP || (countriesP = fetch('geo/countries.json').then(r => r.json()));
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
  map.getSource('aoi').setData({ type: 'Feature', properties: {}, geometry: { type: 'MultiPolygon', coordinates: c.p } });
  const box = $('readout');
  box.hidden = false;
  box.textContent = '';
  const head = document.createElement('b');
  head.textContent = c.n;
  const sub = document.createElement('div');
  sub.textContent = (c.area / 1e6).toLocaleString('en-US', { maximumFractionDigits: 0 }) + ' km²';
  const hint = document.createElement('div');
  hint.style.color = 'var(--muted)';
  hint.textContent = 'Click elsewhere to deselect';
  box.append(head, sub, hint);
}
async function selectCountryAt(ll) {
  const x = wrapLng(ll.lng), y = ll.lat, list = await loadCountries();
  const c = list.find(k => x >= k.b[0] && x <= k.b[2] && y >= k.b[1] && y <= k.b[3] && ringsContain(k.p, x, y));
  if (!c) return;                                   // clicked on the ocean: keep the current selection
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

/* ----- Labels and borders toggle ----- */
$('labelsChk').onchange = e => map.setLayoutProperty('labels', 'visibility', e.target.checked ? 'visible' : 'none');

/* ----- Idle auto-rotate: spins slowly when zoomed out, untouched for 6 s, and nothing is selected ----- */
let lastTouch = -Infinity, flying = false, lastFrame = performance.now();
for (const ev of ['mousedown', 'wheel', 'touchstart', 'keydown'])
  addEventListener(ev, () => { lastTouch = performance.now(); }, { passive: true, capture: true });
map.on('moveend', () => { flying = false; });
(function spin(t) {
  const dt = Math.min(100, t - lastFrame); lastFrame = t;
  if ($('rotateChk').checked && !drag && !flying && !selectMode && !currentBox && map.getZoom() < 4 && t - lastTouch > 6000) {
    const c = map.getCenter();
    map.setCenter([c.lng + dt * 0.004, c.lat]);       // about 4 degrees per second
  }
  requestAnimationFrame(spin);
})(lastFrame);

/* ----- Search: a place name (OpenStreetMap Nominatim) or "lat, lon" ----- */
function flyWith(fn) { flying = true; lastTouch = performance.now(); fn(); }
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
  const li = msg => { const x = document.createElement('li'); x.textContent = msg; list.append(x); return x; };
  try {
    const r = await fetch('https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&q=' + encodeURIComponent(q));
    const hits = await r.json();
    if (!hits.length) { li('No place found'); return; }
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

const ready = (async () => {
  const r = await fetch('data/meta.json');
  if (!r.ok) throw new Error('data/meta.json not found');
  const ix = data.index = await r.json(), M = ix.months;
  const cb = await (await fetch('data/coarse.bin')).arrayBuffer();
  data.blockList = ix.blocks.map(([la, lo], i) => ({
    la, lo, key: `${la}_${lo}`, tiles: null,
    mod: new Uint32Array(cb, i * 12 * M, M), vii: new Uint32Array(cb, i * 12 * M + 4 * M, M),
    harm: new Float32Array(cb, i * 12 * M + 8 * M, M)
  }));
  // Lookup: day number since 2000-01-01 -> month number since 2000-01.
  const nDays = Math.ceil(M * 31) + 62;
  data.dayMonth = new Uint16Array(nDays);
  for (let d = 0; d < nDays; d++) {
    const dt = new Date(Date.UTC(2000, 0, 1 + d));
    data.dayMonth[d] = (dt.getUTCFullYear() - 2000) * 12 + dt.getUTCMonth();
  }
  data.era = Uint8Array.from({ length: M }, (_, m) => +(m >= ix.viirsStart && m <= ix.viirsEnd));
  const [fy, fm] = ix.firstDate.split('-').map(Number);
  const [ly, lm, ld] = ix.lastDate.split('-').map(Number);
  ix.firstMonth = (fy - 2000) * 12 + fm - 1;
  ix.lastMonth = M - 1;
  // If the newest data stops mid-month, that month is flagged and kept out of the statistics.
  ix.partialMonth = ld < new Date(Date.UTC(ly, lm, 0)).getUTCDate() ? ix.lastMonth : -1;
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

function loadBlock(blk) {
  if (!blk.tiles) blk.tiles = fetch(`data/blocks/${blk.key}.bin`).then(r => r.arrayBuffer()).then(buf => {
    const M = data.index.months, dv = new DataView(buf), n = dv.getUint32(0, true), S = 4 + 108 * n;
    return Array.from({ length: n }, (_, i) => {
      const o = 4 + 108 * i, la = dv.getInt16(o, true), lo = dv.getInt16(o + 2, true);
      return { la, lo, key: `${la}_${lo}`, k: dv.getUint16(o + 4, true), n: dv.getUint32(o + 8, true), head: null,
        rM: new Float32Array(buf, o + 12, 12), rT: new Float32Array(buf, o + 60, 12),
        mod: new Uint32Array(buf, S + i * 12 * M, M), vii: new Uint32Array(buf, S + i * 12 * M + 4 * M, M),
        harm: new Float32Array(buf, S + i * 12 * M + 8 * M, M) };
    });
  });
  return blk.tiles;
}
// A split tile starts with a directory (where each cell's hotspots begin) and per-cell monthly counts.
function loadHead(t) {
  if (!t.head) {
    const k2 = t.k * t.k, M = data.index.months, len = 4 * (k2 + 1) + 4 * k2 * M;
    t.head = fetchRange(`data/tiles/${t.key}.bin`, 0, len).then(buf => ({
      len, dir: new Uint32Array(buf, 0, k2 + 1),
      mod: new Uint16Array(buf, 4 * (k2 + 1), k2 * M), vii: new Uint16Array(buf, 4 * (k2 + 1) + 2 * k2 * M, k2 * M)
    }));
  }
  return t.head;
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
    if (rb === 2 && !wantPoints && !h.perTile) { h.series(blk.mod, blk.vii, blk.harm, null); continue; }
    for (const t of await loadBlock(blk)) {
      const rt = rb === 2 ? 2 : R.rel(t.lo, t.la, 1);
      if (!rt) continue;
      if (rt === 2 && !wantPoints) { h.series(t.mod, t.vii, t.harm, t); continue; }
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
    const buf = await fetchRange(`data/tiles/${j.t.key}.bin`, j.start, j.end);
    h.points(j.t, new DataView(buf), Math.floor(buf.byteLength / REC), j.keep);
    if (onProgress) onProgress(++done, jobs.length);
  });
  return hit;
}

async function query(sel, onProgress) {
  const ix = data.index, M = ix.months, era = data.era;
  const out = { modis: new Float64Array(M), viirs: new Float64Array(M), raw: new Float64Array(M),
    harm: new Float64Array(M), check: new Float64Array(M), tiles: 0 };
  // check = MODIS converted to VIIRS units for every month, including the VIIRS years, so
  // the two can be compared where both sensors flew (a test of the harmonization).
  // The harmonization: MODIS counts are multiplied by the tile's VIIRS/MODIS ratio for that
  // month of the year; months in the VIIRS era use the VIIRS count as it is.
  const ratio = (t, m) => (m < ix.aquaStart ? t.rT : t.rM)[m % 12];
  out.tiles = await walk(sel, false, {
    perTile: true,
    series(mod, vii, harm, t) {
      for (let m = 0; m < M; m++) {
        out.modis[m] += mod[m]; out.viirs[m] += vii[m]; out.harm[m] += harm[m]; out.raw[m] += era[m] ? vii[m] : mod[m];
        out.check[m] += era[m] ? mod[m] * t.rM[m % 12] : harm[m];
      }
    },
    cell(t, head, c) {
      for (let m = 0, o = c * M; m < M; m++, o++) {
        const mod = head.mod[o], v = head.vii[o];
        out.modis[m] += mod; out.viirs[m] += v; out.check[m] += mod * ratio(t, m);
        if (era[m]) { out.raw[m] += v; out.harm[m] += v; } else { out.raw[m] += mod; out.harm[m] += mod * ratio(t, m); }
      }
    },
    points(t, dv, n, keep) {
      for (let i = 0, o = 0; i < n; i++, o += REC) {
        if (keep && !keep(dv.getUint16(o, true), dv.getUint16(o + 2, true))) continue;
        const m = data.dayMonth[dv.getUint16(o + 4, true)];
        if ((dv.getUint8(o + 8) & 3) === 2) { out.viirs[m]++; if (era[m]) { out.raw[m]++; out.harm[m]++; } }
        else { out.modis[m]++; out.check[m] += ratio(t, m); if (!era[m]) { out.raw[m]++; out.harm[m] += ratio(t, m); } }
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
async function heatFeatures(m, blocks) {
  const ix = data.index, feats = [];
  const push = (x, y, w) => feats.push({ type: 'Feature', properties: { w }, geometry: { type: 'Point', coordinates: [x, y] } });
  if (!blocks) {
    const buf = await (await fetch(`data/heat0/${m}.bin`)).arrayBuffer();
    const u = new Uint16Array(buf), f = new Float32Array(buf);
    for (let i = 0; i < f.length; i += 2) push((u[2 * i] + 0.5) * ix.heat0 - 180, (u[2 * i + 1] + 0.5) * ix.heat0 - 90, f[i + 1]);
    return feats;
  }
  await pool(blocks, 6, async blk => {
    const url = `data/heat1/${blk.key}.bin`, hl = 4 * (ix.months + 1);
    if (!heat.heads.has(blk.key)) heat.heads.set(blk.key, fetchRange(url, 0, hl).then(b => new Uint32Array(b)));
    const offs = await heat.heads.get(blk.key);
    if (offs[m + 1] === offs[m]) return;
    const dv = new DataView(await fetchRange(url, hl + offs[m] * 4, hl + offs[m + 1] * 4));
    for (let o = 0; o < dv.byteLength; o += 4)
      push(blk.lo + (dv.getUint8(o) + 0.5) * ix.heat1, blk.la + (dv.getUint8(o + 1) + 0.5) * ix.heat1, dv.getUint16(o + 2, true) / 8);
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
    const total = data.blockList.reduce((a, b) => a + b.harm[m], 0);
    note = Math.round(total).toLocaleString('en-US') + ' hotspots' + (m === ix.partialMonth ? ' (incomplete month)' : '');
    const p = blocks ? HEAT_PAINT.detail : HEAT_PAINT.world;
    // Strength relative to the busiest places this month (99th percentile), square-rooted so
    // medium activity still shows: quiet areas glow dark red, the busiest ones yellow.
    const ws = feats.map(f => f.properties.w).sort((a, b) => a - b), p99 = ws.length ? ws[Math.floor(ws.length * 0.99)] || 1 : 1;
    map.setPaintProperty('heat', 'heatmap-weight', ['min', 1, ['sqrt', ['/', ['get', 'w'], p99]]]);
    map.setPaintProperty('heat', 'heatmap-radius', p.radius);
  }
  map.getSource('heat').setData({ type: 'FeatureCollection', features: feats });
  $('heatCaption').textContent = on ? `${MONTHS_LONG[moy]} ${year} · ${note} · ${ix.coverage}` : 'Fire map hidden';
}
Promise.all([ready, new Promise(res => map.once('load', res))]).then(() => {
  if (data.error) { $('heatCaption').textContent = 'Fire map data could not be loaded'; return; }
  const ix = data.index, fy = 2000 + Math.floor(ix.firstMonth / 12), ly = 2000 + Math.floor(ix.lastMonth / 12);
  // Start on the newest complete month.
  const startM = ix.partialMonth === ix.lastMonth ? ix.lastMonth - 1 : ix.lastMonth;
  const yearBox = $('heatYear'), slider = $('heatMonth');
  yearBox.min = fy; yearBox.max = ly; yearBox.value = 2000 + Math.floor(startM / 12);
  slider.value = startM % 12;
  MONTHS.forEach((mn, i) => {
    const s = document.createElement('span');
    s.textContent = mn;
    s.onclick = () => { slider.value = i; showHeat(); };
    $('monthTicks').append(s);
  });
  slider.oninput = showHeat;
  $('heatChk').onchange = showHeat;
  // Typing a year: update as soon as it is a valid year; tidy it when the box is left.
  yearBox.oninput = () => { const y = +yearBox.value; if (Number.isInteger(y) && y >= fy && y <= ly) showHeat(); };
  yearBox.onchange = () => { yearBox.value = Math.max(fy, Math.min(ly, Math.round(+yearBox.value) || ly)); showHeat(); };
  // Moving or zooming the globe can change which level of detail is needed.
  let moveTimer = 0;
  map.on('moveend', () => { clearTimeout(moveTimer); moveTimer = setTimeout(showHeat, 250); });
  showHeat();
});

/* ================= 5. Panel ================= */
// m0..m1: the chosen date range, as month numbers since January 2000; y0..y1 are its years.
const state = { sel: null, result: null, mode: 'harm', view: 'count', m0: 0, m1: 0, y0: 0, y1: 0, model: null, token: 0 };
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
function seqColor(t) {
  const x = Math.max(0, Math.min(1, t)) * (SEQ.length - 1), i = Math.min(SEQ.length - 2, Math.floor(x));
  return mix(SEQ[i], SEQ[i + 1], x - i);
}
const divColor = d => mix('#383835', d < 0 ? '#3987e5' : '#e66767', Math.min(1, Math.abs(d)));
// Anomaly on a log scale: -1 means a quarter of normal or less, +1 means four times normal or more.
const anomScore = (v, med) => Math.max(-1, Math.min(1, Math.log2((v + 1) / (med + 1)) / 2));

function setStatus(msg) { $('status').hidden = !msg; $('status').textContent = msg || ''; }
function openPanel(open) {
  $('panel').classList.toggle('open', open);
  $('panelTab').classList.toggle('show', !open && !!state.sel);
  const w = open && innerWidth > 760 ? $('panel').offsetWidth : 0;
  map.easeTo({ padding: { top: 0, bottom: 0, left: 0, right: w }, duration: 300 });
}
$('panelClose').onclick = () => openPanel(false);
$('panelTab').onclick = () => openPanel(true);

window.addEventListener('aoi-selected', async e => {
  const sel = state.sel = e.detail, token = ++state.token;
  state.result = null;
  $('results').hidden = true;
  if (!sel) { openPanel(false); return; }
  $('bN').value = sel.north.toFixed(4); $('bS').value = sel.south.toFixed(4);
  $('bW').value = sel.west.toFixed(4); $('bE').value = sel.east.toFixed(4);
  $('areaText').textContent = (sel.country ? sel.country + ' · ' : '') + fmtArea(sel.areaM2);
  $('areaNote').textContent = sel.country
    ? `Hotspots inside the border of ${sel.country}. The four values above are the box around it; Apply turns it into a rectangle.`
    : 'Drag the orange corner dots on the globe to resize, or type exact coordinates.';
  openPanel(true);
  setStatus('Reading hotspots…');
  await ready;
  if (token !== state.token) return;
  if (data.error) { setStatus('The hotspot data could not be loaded (' + data.error.message + ').'); return; }
  try {
    const res = await query(sel, (d, n) => { if (token === state.token) setStatus(`Reading hotspots… ${d} of ${n} map squares`); });
    if (token !== state.token) return;
    if (!res.tiles) { setStatus('No hotspots have been recorded in this area (open ocean, ice, or outside the data loaded).'); return; }
    state.result = res;
    setStatus('');
    $('results').hidden = false;
    render();
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
segmented('modeSeg', 'mode'); segmented('viewSeg', 'view');
// Date range: a start month + year and an end month + year.
function setRange(m0, m1) {
  if (m0 > m1) [m0, m1] = [m1, m0];
  Object.assign(state, { m0, m1, y0: 2000 + Math.floor(m0 / 12), y1: 2000 + Math.floor(m1 / 12) });
  $('mo0').value = m0 % 12; $('y0').value = state.y0; $('mo1').value = m1 % 12; $('y1').value = state.y1;
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
  Object.assign(state, { m0: (fy - 2000) * 12, m1: (ly - 2000) * 12 + 11, y0: fy, y1: ly });
  $('mo0').value = 0; $('y0').value = fy; $('mo1').value = 11; $('y1').value = ly;
});

// Everything shown in the panel is derived here from the monthly series.
function buildModel() {
  const ix = data.index, s = state.result[state.mode];
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

function render() {
  if (!state.result) return;
  const md = state.model = buildModel(), harm = state.mode === 'harm', anom = state.view === 'anom';
  const unit = harm ? 'VIIRS-equivalent hotspots' : 'hotspots (raw)';

  $('modeNote').textContent = harm
    ? 'Harmonized: MODIS years (before Feb 2012) are scaled to what VIIRS would have detected, so every year is comparable.'
    : 'Raw: MODIS counts before Feb 2012, VIIRS counts after, with no correction. The jump in 2012 is the sensor change, not more fire.';

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
      const td = el('td', { className: 'c' + (c.partial ? ' partial' : '') });
      let bright;
      if (anom) {
        td.style.background = divColor(c.score); bright = false;
        td.textContent = c.anom === null ? (c.v > 0 ? 'new' : '0') : pct(Math.max(-999, Math.min(999, c.anom)));
        td.style.fontSize = '10px';
      } else {
        const tt = md.heat(c.v);
        if (c.v > 0) td.style.background = seqColor(tt);
        bright = c.v > 0 && textOn(seqColor(tt)) === '#0b0b0b';
        td.textContent = compact(c.v);
      }
      td.style.color = bright ? '#0b0b0b' : '#f0efec';
      td.dataset.tip = `${MONTHS_LONG[moy]} ${r.y}: ${nf(c.v)} ${unit}\nMedian for ${MONTHS[moy]}: ${nf(md.med[moy])}` +
        (c.anom === null ? '' : `\nDifference: ${pct(c.anom)}`) + (c.partial ? '\nIncomplete month' : '');
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
    `${md.ix.firstDate} to ${md.ix.lastDate}. Harmonization ratios measured over Feb 2012 – ${MONTHS[md.ix.overlap[1] % 12]} ${2000 + Math.floor(md.ix.overlap[1] / 12)}.`;
}

/* ================= 6. Charts (plain SVG) ================= */
const NS = 'http://www.w3.org/2000/svg';
const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';
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
  // Compare the typical year with the newest year in the range that has any data.
  const row = [...md.rows].reverse().find(r => r.cells.some(c => c.exists)) || md.rows[0];
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
  $('seasonYear').textContent = row.y;
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

// The harmonized record month by month.
function drawMonthly(md) {
  const svg = $('monthlyChart'), W = 560, H = 220, pad = { l: 44, r: 10, t: 16, b: 26 }, r = state.result, ix = md.ix;
  const months = [];
  for (const row of md.rows) for (const c of row.cells) if (c.exists && !c.partial) months.push(c.m);
  legend('monthlyLegend', [[`linear-gradient(90deg,${SEQ.slice(2).join(',')})`, 'Hotspots per month (colour = how many)']]);
  if (!months.length) { svg.textContent = ''; return; }
  const top = niceMax(Math.max(...months.map(m => r.harm[m]), 1));
  const y = axes(svg, W, H, pad, top);
  const m0 = months[0], m1 = months[months.length - 1], x = m => pad.l + (m1 > m0 ? (m - m0) / (m1 - m0) : 0.5) * (W - pad.l - pad.r);
  if (ix.viirsStart > m0 && ix.viirsStart <= m1) {
    svg.append(svgEl('line', { x1: x(ix.viirsStart), x2: x(ix.viirsStart), y1: pad.t - 6, y2: H - pad.b, stroke: '#898781', 'stroke-dasharray': '3 3' }));
    label(svg, x(ix.viirsStart) + 4, pad.t + 2, 'VIIRS-based from here', 'start', '#898781', 10);
  }
  const path = (get, color, w, opacity = 1) => {
    let d = '', prev = -2;
    for (const m of months) { const v = get(m); if (v === null) { prev = -2; continue; } d += `${m === prev + 1 ? 'L' : 'M'}${x(m).toFixed(1)},${y(v).toFixed(1)}`; prev = m; }
    svg.append(svgEl('path', { d, fill: 'none', stroke: color, 'stroke-width': w, 'stroke-linejoin': 'round', 'stroke-opacity': opacity }));
  };
  const grad = svgEl('linearGradient', { id: 'fireGrad', gradientUnits: 'userSpaceOnUse', x1: 0, x2: 0, y1: H - pad.b, y2: pad.t });
  SEQ.slice(2).forEach((c, i, a) => grad.append(svgEl('stop', { offset: i / (a.length - 1), 'stop-color': c })));
  const defs = svgEl('defs'); defs.append(grad); svg.append(defs);
  path(m => r.harm[m], 'url(#fireGrad)', 1.6);
  const y0 = 2000 + Math.floor(m0 / 12), y1 = 2000 + Math.floor(m1 / 12), every = y1 - y0 > 18 ? 5 : y1 - y0 > 8 ? 2 : 1;
  for (let yr = y0; yr <= y1; yr++) if (yr % every === 0 || y1 - y0 < 3) {
    const m = (yr - 2000) * 12;
    if (m >= m0 && m <= m1) { svg.append(svgEl('line', { x1: x(m), x2: x(m), y1: H - pad.b, y2: H - pad.b + 4, stroke: '#383835' })); label(svg, x(m), H - 8, yr); }
  }
  const step = (W - pad.l - pad.r) / Math.max(1, m1 - m0);
  for (const m of months) {
    const g = svgEl('g', { class: 'hit' });
    g.dataset.tip = `${MONTHS_LONG[m % 12]} ${2000 + Math.floor(m / 12)}\n${nf(r.harm[m])} hotspots (harmonized)`;
    g.append(svgEl('line', { class: 'cross', x1: x(m), x2: x(m), y1: pad.t, y2: H - pad.b, stroke: '#898781', opacity: 0 }));
    g.append(svgEl('rect', { x: x(m) - step / 2, y: pad.t, width: step, height: H - pad.t - pad.b, fill: 'transparent' }));
    svg.append(g);
  }
  $('monthlyNote').textContent = 'Every month of the selected years in one line, to spot the biggest fire months and long-term changes. From February 2012 the counts come from VIIRS; before that, MODIS converted to VIIRS units.';
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
  const r = state.result, md = state.model;
  const out = tableSink(write);
  out.begin(['year', 'month', 'modis_raw', 'viirs_raw', 'harmonized_viirs_equivalent', 'source', 'complete_month']);
  const rows = [];
  for (const row of md.rows) for (const c of row.cells) if (c.exists) {
    rows.push([row.y, c.m % 12 + 1, r.modis[c.m], r.viirs[c.m], +r.harm[c.m].toFixed(1),
      inViirsEra(c.m) ? 'VIIRS' : 'MODIS scaled', c.partial ? 'no' : 'yes']);
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
    out.begin(['latitude', 'longitude', 'acq_date', 'satellite', 'instrument', 'confidence', 'frp', 'daynight', 'type', 'harmonized_weight']);
    await walk(state.sel, true, {
      points(t, dv, n, keep) {
        const rows = [];
        for (let i = 0, o = 0; i < n; i++, o += REC) {
          const la = dv.getUint16(o, true), lo = dv.getUint16(o + 2, true);
          if (keep && !keep(la, lo)) continue;
          const day = dv.getUint16(o + 4, true), m = data.dayMonth[day];
          if (m < m0 || m > m1) continue;
          const fl = dv.getUint8(o + 8), sat = fl & 3, viirs = sat === 2, era = inViirsEra(m);
          // Weight = this detection's contribution to the harmonized count.
          const weight = viirs ? (era ? 1 : 0) : era ? 0 : +(m < ix.aquaStart ? t.rT : t.rM)[m % 12].toFixed(4);
          rows.push([+(t.la + la / 65535).toFixed(5), +(t.lo + lo / 65535).toFixed(5),
            { date: new Date(Date.UTC(2000, 0, 1 + day)).toISOString().slice(0, 10) },
            SAT[sat], viirs ? 'VIIRS' : 'MODIS', CONF[fl >> 5 & 3], dv.getUint16(o + 6, true) / 10, fl & 4 ? 'N' : 'D', fl >> 3 & 3, weight]);
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
  text((anom ? 'Fire activity anomaly' : 'Burning activity calendar') + (state.mode === 'harm' ? ' (harmonized MODIS + VIIRS)' : ' (raw counts)'), 24, 38, '#f0efec', 22, 'left', 600);
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
  text('Fire season: typical year (orange), usual range (grey), ' + $('seasonYear').textContent + ' (yellow)', 24, y + 14, '#c3c2b7', 13);
  text('Unusual years: difference from the average', 616, y + 14, '#c3c2b7', 13);
  await drawSvg('seasonChart', 24, y + 26, 560, 220);
  await drawSvg('anomChart', 616, y + 26, 560, 220);
  text('Monthly record, harmonized (colour = number of hotspots)', 24, y + 280, '#c3c2b7', 13);
  await drawSvg('monthlyChart', 24, y + 292, 1152, 452);
  await write(await new Promise(res => cv.toBlob(res, 'image/png')));
});
