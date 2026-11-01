// Leaflet parcel map. Germany: open ALKIS fragment (Magdeburg) coloured by the PRELIMINARY geometric signal; India: illustrative demo parcels.
// Also supports drawing an outline and marking a point. Leaflet is vendored (../vendor/leaflet.js) and exposed as window.L.
import { api, h, toast, num, parcelLabel } from './core.js';

const COLORS = { green: '#2f7d3b', yellow: '#c58a00', red: '#b3261e' };

export async function parcelMap(el, { country, onSelect, saved = [], leased = [] }) {
  const L = window.L;
  const map = L.map(el, { zoomControl: true, attributionControl: true, scrollWheelZoom: false }).setView(country === 'DE' ? [52.09, 11.555] : [23.35, 70.56], country === 'DE' ? 13 : 12);
  // Default: OpenStreetMap tiles rendered in a quiet grey "schematic" style (CSS filter on .tiles-schematic); plain street map, satellite and "no tiles" are in the switcher.
  const light = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'tiles-schematic', attribution: '© OpenStreetMap contributors' }).addTo(map);
  const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' });
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Esri World Imagery' });
  L.control.layers({ 'Schematic': light, 'Street map': osm, 'Satellite': sat, 'No tiles (offline)': L.layerGroup() }, {}, { collapsed: true }).addTo(map);
  // the wheel scrolls the page; it zooms the map only after a click on it (and again off when the pointer leaves)
  map.on('click focus', () => map.scrollWheelZoom.enable()); map.on('mouseout', () => map.scrollWheelZoom.disable());
  let tileWarned = false;
  for (const l of [light, osm, sat]) l.on('tileerror', () => { if (!tileWarned) { tileWarned = true; toast('Map tiles could not be loaded (offline?). Parcels still work: use the layer switcher > "No tiles".', true); } });
  let selected = null, parcelLayer = null, startView = () => {}, activeRegion = '', drawing = null; const byRef = {}, groups = {}, entries = [];
  const info = h('div', { class: 'small muted', style: 'margin-top:.4rem' });
  const search = h('input', { type: 'search', placeholder: 'Search a parcel, number or place', 'aria-label': 'Search parcels' });
  const choices = h('select', { 'aria-label': 'Choose a parcel from the list' });
  const browser = h('div', { class: 'map-browser' }, h('label', { class: 'f' }, 'Find a parcel', search), h('label', { class: 'f' }, 'Or choose from this area', choices));
  const regionButtons = [];
  function filterChoices() {
    const term = search.value.trim().toLowerCase(), visible = entries.filter(e => (!activeRegion || e.region === activeRegion) && e.search.includes(term));
    choices.replaceChildren(h('option', { value: '' }, visible.length ? `Choose a parcel · ${visible.length} on this map` : 'No parcels match your search'), ...visible.map(e => h('option', { value: e.ref }, `${parcelLabel(e.payload.label)} · ${num(e.payload.area_ha)} ha`)));
  }
  search.addEventListener('input', filterChoices);
  choices.addEventListener('change', () => { const e = entries.find(x => x.ref === choices.value); if (e) select(e.layer, e.payload); });
  function addEntry(layer, payload, region, aliases = []) {
    const ref = payload.ref;
    for (const key of [ref, ...aliases]) if (key) byRef[key] = layer;
    entries.push({ ref, layer, payload, region, search: [ref, ...aliases, payload.label].join(' ').toLowerCase() });
    (groups[region] ||= []).push(layer);
    layer.bindTooltip(`${parcelLabel(payload.label)} · ${num(payload.area_ha)} ha`, { sticky: true });
    layer.on('click', () => select(layer, payload));
  }

  const select = (layer, payload) => {
    if (drawing) return;
    if (selected) selected.layer.setStyle(selected.style);
    selected = { layer, style: { ...layer.options } };
    layer.setStyle({ weight: 4, color: '#1f6b8f', fillOpacity: .55 }); layer.bringToFront();
    if (layer.getBounds) map.fitBounds(layer.getBounds().pad(1), { maxZoom: 17 });
    choices.value = payload.ref;
    onSelect(payload);
  };

  if (country === 'DE') {
    const [{ features }, cor] = await Promise.all([api('/geo/de/map'), api('/geo/de/corridors')]);
    for (const m of [500, 200]) {
      const f = cor.corridors.features.find(x => x.properties.meters === m);
      if (f) L.geoJSON(f, { style: { color: m === 500 ? '#c58a00' : '#2f7d3b', weight: 1, fillOpacity: .08, dashArray: '4 4' }, interactive: false }).addTo(map);
    }
    L.geoJSON(cor.roads, { style: { color: '#444', weight: 3 }, interactive: false }).addTo(map);
    parcelLayer = L.geoJSON(features, {
      style: f => ({ color: COLORS[cor.signals[f.properties.cadastral]] || '#888', weight: 1.5, fillOpacity: .28, lineJoin: 'miter', lineCap: 'butt' }),
      onEachFeature: (f, layer) => { const p = f.properties, address = p.address;
        const region = /Thauberg/.test(address) ? 'Thauberg' : /Osterweddinger/.test(address) ? 'Osterweddinger Chaussee' : /Wanzleber|Hängelbergen/.test(address) ? 'Wanzleber Chaussee' : 'Magdeburg West';
        addEntry(layer, {
        source: 'alkis-demo', ref: f.properties.cadastral, geometry: f.geometry,
        label: `Flurstück ${f.properties.parcel_number} (Flur ${f.properties.flur}), ${f.properties.address}`, area_ha: f.properties.area,
        signal: cor.signals[f.properties.cadastral], demo: false }, region, [p.parcel_number, p.address, `Flur ${p.flur}`]); },
    }).addTo(map);
    info.append('Select an area, use the parcel list or click a boundary. Corridor colours are a preliminary screening signal. ', h('a', { href: '#/data' }, 'Boundary sources →'));
  } else {
    const gj = await api('/geo/in/demo-parcels');
    parcelLayer = L.geoJSON(gj, {
      style: f => f.properties.registered ? { color: '#2f7d3b', weight: 2, fillOpacity: .35 } : { color: '#1f6b8f', weight: 1.5, fillOpacity: .26, lineJoin: 'miter', lineCap: 'butt' },
      onEachFeature: (f, layer) => { addEntry(layer, {
        source: 'in-demo', ref: f.properties.id, geometry: f.geometry, label: `${f.properties.label} - ${f.properties.survey_number}, ${f.properties.village}`,
        area_ha: f.properties.area_ha, demo: true, registered: !!f.properties.registered }, f.properties.district, [f.properties.survey_number]); },
    }).addTo(map);
    info.append('Select an area, use the field list or draw your own boundary. ', h('a', { href: '#/data' }, 'Boundary sources →'));
  }
  const REGION = { Kutch: 'Kutch · Gujarat', Anantapur: 'Anantapur · Andhra Pradesh', Beed: 'Beed · Maharashtra' };
  function goTo(region) {
    activeRegion = region; filterChoices();
    const layers = region ? groups[region] : entries.map(e => e.layer);
    if (layers.length) map.fitBounds(L.featureGroup(layers).getBounds().pad(.12), { maxZoom: 16 });
    for (const [button, key] of regionButtons) button.setAttribute('aria-pressed', String(key === region));
  }
  const bar = L.control({ position: 'topleft' });
  bar.onAdd = () => { const box = L.DomUtil.create('div', 'map-regions'); L.DomEvent.disableClickPropagation(box); L.DomEvent.disableScrollPropagation(box);
    for (const region of ['', ...Object.keys(groups)]) { const button = L.DomUtil.create('button', '', box); button.type = 'button'; button.textContent = `${region ? REGION[region] || region : 'All parcels'} · ${region ? groups[region].length : entries.length}`; button.onclick = () => goTo(region); regionButtons.push([button, region]); } return box; };
  bar.addTo(map);
  startView = () => goTo(country === 'IN' ? Object.keys(groups)[0] : '');
  filterChoices();
  const mine = L.featureGroup().addTo(map);
  for (const l of leased) L.geoJSON({ type: 'Feature', geometry: l.geometry }, { style: { color: '#c2410c', weight: 2, fillOpacity: .3, dashArray: '5 3' } }).bindTooltip(l.label || 'Leased parcel').addTo(mine);
  for (const p of saved.filter(p => p.source === 'drawn')) L.geoJSON({ type: 'Feature', geometry: p.geometry }, { style: { color: '#7a3db8', weight: 2, fillOpacity: .2 } }).bindTooltip(p.label).addTo(mine);

  // --- drawing
  function draw(onDone) {
    const pts = []; const line = L.polyline([], { color: '#7a3db8' }).addTo(map); const dots = L.layerGroup().addTo(map);
    map.getContainer().style.cursor = 'crosshair'; toast('Click the corners of the site. Press "Finish outline" when done.');
    const click = e => { pts.push([e.latlng.lat, e.latlng.lng]); line.setLatLngs(pts); L.circleMarker(e.latlng, { radius: 4, color: '#7a3db8' }).addTo(dots); };
    map.on('click', click);
    drawing = {
      finish() {
        cleanup();
        if (pts.length < 3) return toast('An outline needs at least three corners.', true);
        const ring = pts.map(([la, lo]) => [lo, la]); onDone({ type: 'Polygon', coordinates: [[...ring, ring[0]]] });
      },
      cancel() { cleanup(); },
    };
    function cleanup() { map.off('click', click); map.getContainer().style.cursor = ''; line.remove(); dots.remove(); drawing = null; }
    return drawing;
  }
  // the container may still be laying out when the map is built, so size it first and only then fit the view
  const settle = () => { map.invalidateSize(); if (selected) map.fitBounds(selected.layer.getBounds().pad(1), { maxZoom: 17 }); else if (leased.length && mine.getLayers().length) map.fitBounds(mine.getBounds().pad(1.5), { maxZoom: 16 }); else startView(); };
  setTimeout(settle, 120);
  let resize; try { resize = new ResizeObserver(() => map.invalidateSize()); resize.observe(el); } catch { /* old browser: the layer switcher still works */ }
  const key = L.control({ position: 'bottomleft' });
  key.onAdd = () => { const d = L.DomUtil.create('div', 'map-key'); d.innerHTML = country === 'DE'
    ? '<b>Corridor signal</b><span><i style="background:#2f7d3b"></i>inside 500 m</span><span><i style="background:#c58a00"></i>partly</span><span><i style="background:#b3261e"></i>outside</span><span><i class="ln"></i>A14 motorway</span><span><i style="background:#7a3db8"></i>your outline</span>'
    : '<b>Field boundaries</b><span><i style="background:#1f6b8f"></i>field boundary</span><span><i style="background:#2f7d3b"></i>5am.earth record</span><span><i style="background:#7a3db8"></i>your outline</span>'; return d; };
  key.addTo(map);
  function find(q) {
    q = (q || '').trim().toLowerCase(); if (!q) return false;
    const entry = entries.find(e => e.search.replace(/_/g, '').includes(q.replace(/_/g, '')));
    const key = entry?.ref;
    if (!key) return false; const l = byRef[key]; map.fitBounds(l.getBounds().pad(2)); l.fire('click'); return true;
  }
  return { map, info, browser, draw, find, get drawing() { return drawing; }, clearSelection() { if (selected) selected.layer.setStyle(selected.style); selected = null; }, destroy() { resize?.disconnect(); map.remove(); } };
}
