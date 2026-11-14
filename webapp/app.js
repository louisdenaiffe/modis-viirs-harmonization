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
        'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 1, 0.5, 6, 1, 10, 1.8],
        'heatmap-radius': ['interpolate', ['exponential', 2], ['zoom'], 1, 2, 4, 4, 7, 12, 10, 90],
        'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
          0, 'rgba(120,0,0,0)', 0.08, 'rgba(140,10,10,0.55)', 0.3, '#c81818', 0.6, '#ff3b2f', 0.85, '#ff8f7a', 1, '#ffe1d9'],
        'heatmap-opacity': 0.92
      } },
      { id: 'labels', type: 'raster', source: 'labels' },
      { id: 'aoi-fill', type: 'fill', source: 'aoi', paint: { 'fill-color': '#ffb020', 'fill-opacity': 0.18 } },
      { id: 'aoi-line', type: 'line', source: 'aoi', paint: { 'line-color': '#ffb020', 'line-width': 2 } }
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
  drawBox(b);
  placeHandles(b);
  window.fireGlobe.selection = b && {
    west: wrapLng(b.west), east: wrapLng(b.east), south: b.south, north: b.north,
    crossesAntimeridian: wrapLng(b.east) < wrapLng(b.west), areaM2: areaM2(b)
  };
  window.dispatchEvent(new CustomEvent('aoi-selected', { detail: window.fireGlobe.selection }));
}

function startDrag(lngLat, point) {
  lockPan(true);
  mapEl.classList.add('selecting');
  placeHandles(null);
  drag = { start: lngLat, point, moved: false, box: null };
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
    drawBox(currentBox); placeHandles(currentBox);
    mapEl.classList.toggle('selecting', selectMode);
    if (!selectMode) lockPan(false);
    return;
  }
  setSelectMode(false);
  commit(enforceMin(d.box));
}
map.on('mousedown', e => {
  if (e.originalEvent.button !== 0 || !(selectMode || e.originalEvent.shiftKey)) return;
  e.preventDefault();
  startDrag(e.lngLat, e.point);
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
  if (!b || selectMode || e.originalEvent.shiftKey || performance.now() - committedAt < 400) return;
  const dLng = wrapLng(e.lngLat.lng - b.west), inside = e.lngLat.lat >= b.south && e.lngLat.lat <= b.north &&
    ((dLng + 360) % 360) <= b.east - b.west;
  if (!inside) commit(null);
});
selectBtn.onclick = () => setSelectMode(!selectMode);
$('clearBtn').onclick = () => commit(null);

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

// Visit everything inside the selection. Squares fully inside are reported through
// h.series / h.cell (stored totals) unless wantPoints is set; everything else, and
// everything when wantPoints is set, is delivered hotspot by hotspot through h.points.
async function walk(sel, wantPoints, h, onProgress) {
  const jobs = [];
  let hit = 0;
  for (const b of boxesOf(sel)) for (const blk of data.blockList) {
    const rb = relation(blk.lo, blk.la, 10, b);
    if (!rb) continue;
    hit++;
    if (rb === 2 && !wantPoints) { h.series(blk.mod, blk.vii, blk.harm); continue; }
    for (const t of await loadBlock(blk)) {
      const rt = relation(t.lo, t.la, 1, b);
      if (!rt) continue;
      if (rt === 2 && !wantPoints) { h.series(t.mod, t.vii, t.harm); continue; }
      const win = rt === 2 ? null : tileWindow(t, b);
      if (t.k === 1) { jobs.push({ t, start: 0, end: t.n * REC, win }); continue; }
      const head = await loadHead(t), k = t.k, size = 65536 / k;
      let run = -1;
      for (let c = 0; c <= k * k; c++) {
        let need = false;
        if (c < k * k) {
          const y0 = Math.floor(c / k) * size, x0 = (c % k) * size;
          const out = win && (y0 + size - 1 < win.s || y0 >= win.n || x0 + size - 1 < win.w || x0 >= win.e);
          const inside = !win || (y0 >= win.s && y0 + size - 1 < win.n && x0 >= win.w && x0 + size - 1 < win.e);
          if (inside && !wantPoints) h.cell(t, head, c);
          else if (!out) need = head.dir[c + 1] > head.dir[c];
        }
        if (need && run < 0) run = c;
        if (!need && run >= 0) { jobs.push({ t, start: head.len + head.dir[run] * REC, end: head.len + head.dir[c] * REC, win }); run = -1; }
      }
    }
  }
  let done = 0;
  await pool(jobs, 8, async j => {
    const buf = await fetchRange(`data/tiles/${j.t.key}.bin`, j.start, j.end);
    h.points(j.t, new DataView(buf), Math.floor(buf.byteLength / REC), j.win);
    if (onProgress) onProgress(++done, jobs.length);
  });
  return hit;
}

async function query(sel, onProgress) {
  const ix = data.index, M = ix.months, era = data.era;
  const out = { modis: new Float64Array(M), viirs: new Float64Array(M), raw: new Float64Array(M),
    harm: new Float64Array(M), tiles: 0 };
  // The harmonization: MODIS counts are multiplied by the tile's VIIRS/MODIS ratio for that
  // month of the year; months in the VIIRS era use the VIIRS count as it is.
  const ratio = (t, m) => (m < ix.aquaStart ? t.rT : t.rM)[m % 12];
  out.tiles = await walk(sel, false, {
    series(mod, vii, harm) {
      for (let m = 0; m < M; m++) {
        out.modis[m] += mod[m]; out.viirs[m] += vii[m]; out.harm[m] += harm[m]; out.raw[m] += era[m] ? vii[m] : mod[m];
      }
    },
    cell(t, head, c) {
      for (let m = 0, o = c * M; m < M; m++, o++) {
        const mod = head.mod[o], v = head.vii[o];
        out.modis[m] += mod; out.viirs[m] += v;
        if (era[m]) { out.raw[m] += v; out.harm[m] += v; } else { out.raw[m] += mod; out.harm[m] += mod * ratio(t, m); }
      }
    },
    points(t, dv, n, w) {
      for (let i = 0, o = 0; i < n; i++, o += REC) {
        if (w) {
          const la = dv.getUint16(o, true), lo = dv.getUint16(o + 2, true);
          if (!(la >= w.s && la < w.n && lo >= w.w && lo < w.e)) continue;
        }
        const m = data.dayMonth[dv.getUint16(o + 4, true)];
        if ((dv.getUint8(o + 8) & 3) === 2) { out.viirs[m]++; if (era[m]) { out.raw[m]++; out.harm[m]++; } }
        else { out.modis[m]++; if (!era[m]) { out.raw[m]++; out.harm[m] += ratio(t, m); } }
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
  world: { w: 9, radius: ['interpolate', ['exponential', 2], ['zoom'], 0, 1.5, 2, 2.5, 4, 6, 6, 22] },
  detail: { w: 7, radius: ['interpolate', ['exponential', 2], ['zoom'], 4, 3, 7, 12, 10, 90] }
};
function heatBlocks() {
  if (map.getZoom() < 4.6) return null;
  const b = map.getBounds(), c = map.getCenter();
  const near = data.blockList.filter(k => k.la + 10 > b.getSouth() && k.la < b.getNorth() &&
    ((wrapLng(k.lo + 5 - c.lng) + 360) % 360 < 30 || (wrapLng(c.lng - k.lo - 5) + 360) % 360 < 30));
  return near.length && near.length <= 12 ? near : null;
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
    map.setPaintProperty('heat', 'heatmap-weight', ['interpolate', ['linear'], ['ln', ['+', 1, ['get', 'w']]], 0, 0, p.w, 1]);
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
const state = { sel: null, result: null, mode: 'harm', view: 'count', y0: 0, y1: 0, model: null, token: 0 };

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
const SEQ = ['#3d0a0a', '#6b1111', '#9a1b1b', '#c62828', '#e5484d', '#f28b82', '#fcd5cf'];
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
  $('areaText').textContent = fmtArea(sel.areaM2);
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
for (const id of ['y0', 'y1']) $(id).onchange = () => {
  let a = +$('y0').value, b = +$('y1').value;
  if (a > b) [a, b] = [b, a];
  state.y0 = a; state.y1 = b; $('y0').value = a; $('y1').value = b;
  render();
};
ready.then(() => {
  if (data.error) return;
  const ix = data.index, fy = 2000 + Math.floor(ix.firstMonth / 12), ly = 2000 + Math.floor(ix.lastMonth / 12);
  for (const id of ['y0', 'y1']) for (let y = fy; y <= ly; y++) $(id).add(new Option(y, y));
  state.y0 = fy; state.y1 = ly; $('y0').value = fy; $('y1').value = ly;
});

// Everything shown in the panel is derived here from the monthly series.
function buildModel() {
  const ix = data.index, s = state.result[state.mode];
  const exists = m => m >= ix.firstMonth && m <= ix.lastMonth;
  const usable = m => exists(m) && m !== ix.partialMonth;
  const years = [];
  for (let y = state.y0; y <= state.y1; y++) years.push(y);
  const med = [], p25 = [], p75 = [];
  for (let moy = 0; moy < 12; moy++) {
    const vals = years.map(y => (y - 2000) * 12 + moy).filter(usable).map(m => s[m]).sort((a, b) => a - b);
    med.push(quantile(vals, 0.5)); p25.push(quantile(vals, 0.25)); p75.push(quantile(vals, 0.75));
  }
  let max = 0, total = 0;
  const rows = years.map(y => {
    let sum = 0, n = 0;
    const cells = MONTHS.map((_, moy) => {
      const m = (y - 2000) * 12 + moy;
      if (!exists(m)) return { exists: false };
      const v = s[m];
      sum += v; if (usable(m)) n++; max = Math.max(max, v);
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
  return { ix, s, years, rows, med, p25, p75, max, total, latest, peakYear, peakMoy };
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
  kpi('Total, ' + state.y0 + '–' + state.y1, nf(md.total), unit);
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
        const tt = md.max > 0 ? Math.log1p(c.v) / Math.log1p(md.max) : 0;
        if (c.v > 0) td.style.background = seqColor(tt);
        bright = c.v > 0 && tt > 0.62;
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
    ramp.append('1', bar, compact(md.max) + ' (log scale)');
  }
  $('calNote').textContent = (anom ? 'Each month is compared with the median of the same month over ' + state.y0 + '–' + state.y1 + '. ' : '') +
    (md.ix.partialMonth >= 0 ? 'The outlined month is incomplete and is left out of the medians. ' : '') +
    '“–” means no satellite data yet (the record starts in ' + md.ix.firstDate.slice(0, 7) + ').';

  drawSeason(md, unit);
  drawYears(md, unit);

  const rawPts = md.rows.reduce((a, r) => a + r.cells.reduce((x, c) => x + (c.exists ? state.result.modis[c.m] + state.result.viirs[c.m] : 0), 0), 0);
  state.rawPoints = rawPts;
  $('dlPoints').disabled = rawPts > 500000 || rawPts === 0;
  $('dlNote').textContent = rawPts > 500000
    ? `This search holds ${nf(rawPts)} individual hotspots; the hotspot file is limited to 500,000. Select a smaller area or fewer years.`
    : `The hotspot file will contain ${nf(rawPts)} rows (every MODIS and VIIRS detection in the area and years chosen).`;
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
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}
function axes(svg, W, H, pad, top) {
  svg.textContent = '';
  svg.append(svgEl('rect', { width: W, height: H, fill: '#1a1a19' }));
  const y = v => H - pad.b - (v / top) * (H - pad.t - pad.b);
  for (let i = 0; i <= 4; i++) {
    const v = top * i / 4;
    svg.append(svgEl('line', { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: i ? '#2c2c2a' : '#383835', 'stroke-width': 1 }));
    svg.append(svgEl('text', { x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end', fill: '#898781', 'font-size': 11, 'font-family': FONT }, compact(v)));
  }
  return y;
}

function drawSeason(md, unit) {
  const svg = $('seasonChart'), W = 560, H = 220, pad = { l: 44, r: 46, t: 12, b: 26 };
  // Compare the typical year with the newest year in the range that has any data.
  const row = [...md.rows].reverse().find(r => r.cells.some(c => c.exists)) || md.rows[0];
  const yr = row.cells.map(c => (c.exists && !c.partial ? c.v : null));
  const top = niceMax(Math.max(...md.p75, ...yr.map(v => v || 0), 1));
  const y = axes(svg, W, H, pad, top);
  const step = (W - pad.l - pad.r) / 11, x = i => pad.l + i * step;
  $('seasonYear').textContent = row.y;
  const lg = $('seasonLegend'); lg.textContent = '';
  for (const [cls, c, label] of [['', '#e5484d', 'Median'], ['band', '#e5484d', 'Middle half of years'], ['', '#f0efec', String(row.y)]]) {
    const sp = el('span', { className: cls, textContent: label }); sp.style.setProperty('--c', c); lg.append(sp);
  }
  const band = md.p75.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join('') +
    md.p25.map((v, i) => `L${x(11 - i)},${y(md.p25[11 - i])}`).join('') + 'Z';
  svg.append(svgEl('path', { d: band, fill: '#e5484d', 'fill-opacity': 0.22 }));
  const line = (vals, color) => {
    let d = '', pen = false;
    vals.forEach((v, i) => { if (v === null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${x(i)},${y(v)}`; pen = true; });
    svg.append(svgEl('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  };
  line(md.med, '#e5484d');
  line(yr, '#f0efec');
  yr.forEach((v, i) => { if (v !== null) svg.append(svgEl('circle', { cx: x(i), cy: y(v), r: 4, fill: '#f0efec', stroke: '#1a1a19', 'stroke-width': 2 })); });
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

function drawYears(md, unit) {
  const svg = $('yearChart'), W = 560, H = 200, pad = { l: 44, r: 10, t: 16, b: 26 };
  const top = niceMax(Math.max(...md.rows.map(r => r.sum), 1));
  const y = axes(svg, W, H, pad, top);
  const n = md.rows.length, slot = (W - pad.l - pad.r) / n, bw = Math.max(2, Math.min(24, slot - 2));
  const every = n > 18 ? 5 : n > 9 ? 2 : 1;
  let partial = false;
  md.rows.forEach((r, i) => {
    const cx = pad.l + slot * (i + 0.5), x0 = cx - bw / 2, y0 = y(r.sum), base = y(0), rad = Math.min(4, bw / 2, base - y0);
    const d = `M${x0},${base}V${y0 + rad}Q${x0},${y0} ${x0 + rad},${y0}H${x0 + bw - rad}Q${x0 + bw},${y0} ${x0 + bw},${y0 + rad}V${base}Z`;
    const p = svgEl('path', { class: 'bar', d, fill: '#e5484d', 'fill-opacity': r.complete ? 1 : 0.45 });
    p.dataset.tip = `${r.y}: ${nf(r.sum)} ${unit}` + (r.complete ? '' : '\nIncomplete year');
    if (!r.complete) partial = true;
    svg.append(p);
    if (r.y % every === 0 || n <= 9) svg.append(svgEl('text', { x: cx, y: H - 8, 'text-anchor': 'middle', fill: '#898781', 'font-size': 11, 'font-family': FONT }, r.y));
    if (r.y === 2012 && i > 0) {
      const lx = cx - slot / 2;
      svg.append(svgEl('line', { x1: lx, x2: lx, y1: pad.t - 4, y2: base, stroke: '#898781', 'stroke-width': 1, 'stroke-dasharray': '3 3' }));
      svg.append(svgEl('text', { x: lx + 4, y: pad.t + 2, fill: '#898781', 'font-size': 10, 'font-family': FONT }, 'VIIRS starts'));
    }
  });
  $('yearNote').textContent = partial ? 'Paler bars are years without twelve complete months of data.' : '';
  svg.setAttribute('aria-label', `Hotspots per year (${unit})`);
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
function download(blob, name) {
  const a = el('a', { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
const fileStem = () => {
  const s = state.sel, f = v => v.toFixed(3);
  return `fire_${f(s.south)}_${f(s.west)}_${f(s.north)}_${f(s.east)}_${state.y0}-${state.y1}`;
};

$('dlTable').onclick = () => {
  const r = state.result, md = state.model;
  const lines = ['year,month,modis_raw,viirs_raw,harmonized_viirs_equivalent,source,complete_month'];
  for (const row of md.rows) for (const c of row.cells) if (c.exists) {
    lines.push([row.y, c.m % 12 + 1, r.modis[c.m], r.viirs[c.m], r.harm[c.m].toFixed(1),
      inViirsEra(c.m) ? 'VIIRS' : 'MODIS scaled', c.partial ? 'no' : 'yes'].join(','));
  }
  download(new Blob([lines.join('\n') + '\n'], { type: 'text/csv' }), fileStem() + '_monthly.csv');
};

$('dlPoints').onclick = async () => {
  const btn = $('dlPoints'), label = btn.textContent, ix = data.index;
  btn.disabled = true;
  try {
    const m0 = (state.y0 - 2000) * 12, m1 = (state.y1 - 2000) * 12 + 11;
    const SAT = ['Terra', 'Aqua', 'Suomi NPP'], CONF = ['low', 'nominal', 'high'];
    const parts = ['latitude,longitude,acq_date,satellite,instrument,confidence,frp,daynight,type,harmonized_weight\n'];
    await walk(state.sel, true, {
      points(t, dv, n, w) {
        const rows = [];
        for (let i = 0, o = 0; i < n; i++, o += REC) {
          const la = dv.getUint16(o, true), lo = dv.getUint16(o + 2, true);
          if (w && !(la >= w.s && la < w.n && lo >= w.w && lo < w.e)) continue;
          const day = dv.getUint16(o + 4, true), m = data.dayMonth[day];
          if (m < m0 || m > m1) continue;
          const fl = dv.getUint8(o + 8), sat = fl & 3, viirs = sat === 2, era = inViirsEra(m);
          // Weight = this detection's contribution to the harmonized count.
          const weight = viirs ? (era ? 1 : 0) : era ? 0 : +(m < ix.aquaStart ? t.rT : t.rM)[m % 12].toFixed(4);
          rows.push([(t.la + la / 65535).toFixed(5), (t.lo + lo / 65535).toFixed(5),
            new Date(Date.UTC(2000, 0, 1 + day)).toISOString().slice(0, 10),
            SAT[sat], viirs ? 'VIIRS' : 'MODIS', CONF[fl >> 5 & 3], dv.getUint16(o + 6, true) / 10, fl & 4 ? 'N' : 'D', fl >> 3 & 3, weight].join(','));
        }
        if (rows.length) parts.push(rows.join('\n') + '\n');
      }
    }, (d, n) => { btn.textContent = `Preparing… ${d}/${n}`; });
    download(new Blob(parts, { type: 'text/csv' }), fileStem() + '_hotspots.csv');
  } finally { btn.textContent = label; btn.disabled = state.rawPoints > 500000; }
};

$('dlPng').onclick = async () => {
  const md = state.model, sel = state.sel, S = 2, W = 1200, rowH = 24, x0 = 70, cw = 78;
  const calH = (md.rows.length + 2) * rowH, chartH = 300;
  const cv = el('canvas', { width: W * S, height: (120 + calH + chartH) * S }), c = cv.getContext('2d');
  c.scale(S, S);
  c.fillStyle = '#12151c'; c.fillRect(0, 0, W, cv.height / S);
  const text = (s, x, y, color = '#f0efec', size = 13, align = 'left', weight = 400) => {
    c.fillStyle = color; c.font = `${weight} ${size}px ${FONT}`; c.textAlign = align; c.fillText(s, x, y);
  };
  const anom = state.view === 'anom';
  text((anom ? 'Fire activity anomaly' : 'Burning activity calendar') + (state.mode === 'harm' ? ' (harmonized MODIS + VIIRS)' : ' (raw counts)'), 24, 38, '#f0efec', 22, 'left', 600);
  text(`Area: ${sel.south.toFixed(4)}° to ${sel.north.toFixed(4)}° lat, ${sel.west.toFixed(4)}° to ${sel.east.toFixed(4)}° lon · ${fmtArea(sel.areaM2)} · ${state.y0}–${state.y1}`, 24, 62, '#c3c2b7');
  text($('sourceNote').textContent, 24, 82, '#898781', 11);
  let y = 110;
  MONTHS.forEach((mn, i) => text(mn, x0 + cw * (i + 0.5), y, '#898781', 12, 'center'));
  text('Total', W - 30, y, '#898781', 12, 'right');
  for (const r of [...md.rows].reverse()) {
    y += rowH;
    text(String(r.y), 24, y, '#c3c2b7', 12);
    r.cells.forEach((cell, i) => {
      if (!cell.exists) { text('–', x0 + cw * (i + 0.5), y, '#383835', 12, 'center'); return; }
      const tt = md.max > 0 ? Math.log1p(cell.v) / Math.log1p(md.max) : 0;
      if (anom || cell.v > 0) { c.fillStyle = anom ? divColor(cell.score) : seqColor(tt); c.fillRect(x0 + cw * i + 1, y - 16, cw - 2, rowH - 2); }
      const label = anom ? (cell.anom === null ? (cell.v > 0 ? 'new' : '0') : pct(cell.anom)) : nf(cell.v);
      text(label, x0 + cw * (i + 0.5), y, !anom && cell.v > 0 && tt > 0.62 ? '#0b0b0b' : '#f0efec', 12, 'center');
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
  text('Fire season: median (red), middle half of years (band), ' + $('seasonYear').textContent + ' (white)', 24, y + 14, '#c3c2b7', 13);
  text('Hotspots per year', 624, y + 14, '#c3c2b7', 13);
  await drawSvg('seasonChart', 24, y + 26, 560, 220);
  await drawSvg('yearChart', 624, y + 26, 552, 197);
  cv.toBlob(b => download(b, fileStem() + (anom ? '_anomaly' : '_calendar') + '.png'), 'image/png');
};
