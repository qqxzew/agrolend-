// Leaflet parcel map. Germany: open ALKIS fragment (Magdeburg) coloured by the PRELIMINARY geometric signal; India: illustrative demo parcels.
// Also supports drawing an outline and marking a point. Leaflet is vendored (../vendor/leaflet.js) and exposed as window.L.
import { api, h, toast } from './core.js';

const COLORS = { green: '#2f7d3b', yellow: '#c58a00', red: '#b3261e' };

export async function parcelMap(el, { country, onSelect, saved = [], leased = [] }) {
  const L = window.L;
  const map = L.map(el, { zoomControl: true, attributionControl: true }).setView(country === 'DE' ? [52.09, 11.555] : [23.35, 70.56], country === 'DE' ? 13 : 12);
  // Default: OpenStreetMap tiles rendered in a quiet grey "schematic" style (CSS filter on .tiles-schematic); plain street map, satellite and "no tiles" are in the switcher.
  const light = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'tiles-schematic', attribution: '© OpenStreetMap contributors' }).addTo(map);
  const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' });
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Esri World Imagery' });
  L.control.layers({ 'Schematic': light, 'Street map': osm, 'Satellite': sat, 'No tiles (offline)': L.layerGroup() }, {}, { collapsed: true }).addTo(map);
  let tileWarned = false;
  for (const l of [light, osm, sat]) l.on('tileerror', () => { if (!tileWarned) { tileWarned = true; toast('Map tiles could not be loaded (offline?). Parcels still work: use the layer switcher > "No tiles".', true); } });
  let selected = null, parcelLayer = null; const byRef = {};
  const info = h('div', { class: 'small muted', style: 'margin-top:.4rem' });

  const select = (layer, payload) => {
    if (selected) selected.layer.setStyle(selected.style);
    selected = { layer, style: { ...layer.options } };
    layer.setStyle({ weight: 4, color: '#1f6b8f', fillOpacity: .55 });
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
      onEachFeature: (f, layer) => { byRef[f.properties.cadastral] = layer; layer.on('click', () => select(layer, {
        source: 'alkis-demo', ref: f.properties.cadastral, geometry: f.geometry,
        label: `Flurstück ${f.properties.parcel_number} (Flur ${f.properties.flur}), ${f.properties.address}`, area_ha: f.properties.area,
        signal: cor.signals[f.properties.cadastral], demo: false })); },
    }).addTo(map);
    info.textContent = 'Colour = preliminary geometric signal from the A14 carriageway axis (green: inside the 500 m corridor, yellow: partly, red: outside). It is not a permission or a guarantee.';
  } else {
    const gj = await api('/geo/in/demo-parcels');
    parcelLayer = L.geoJSON(gj, {
      style: { color: '#1f6b8f', weight: 2, fillOpacity: .28, lineJoin: 'miter', lineCap: 'butt' },
      onEachFeature: (f, layer) => layer.on('click', () => select(layer, {
        source: 'in-demo', ref: f.properties.id, geometry: f.geometry, label: `${f.properties.label} - ${f.properties.survey_number}, ${f.properties.village}`,
        area_ha: f.properties.area_ha, demo: true })),
    }).addTo(map);
    info.textContent = 'Illustrative rectangles at real coordinates (not survey boundaries; survey numbers invented). Draw your own outline to audit a real site.';
    map.fitBounds(parcelLayer.getBounds().pad(.4));
  }
  const mine = L.featureGroup().addTo(map);
  for (const l of leased) L.geoJSON({ type: 'Feature', geometry: l.geometry }, { style: { color: '#c2410c', weight: 2, fillOpacity: .3, dashArray: '5 3' } }).bindTooltip(l.label || 'Leased parcel').addTo(mine);
  for (const p of saved.filter(p => p.source === 'drawn')) L.geoJSON({ type: 'Feature', geometry: p.geometry }, { style: { color: '#7a3db8', weight: 2, fillOpacity: .2 } }).bindTooltip(p.label).addTo(mine);

  // --- drawing
  let drawing = null;
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
  setTimeout(() => { map.invalidateSize(); if (leased.length && mine.getLayers().length) map.fitBounds(mine.getBounds().pad(1.5), { maxZoom: 16 }); }, 200);
  function find(q) {
    q = (q || '').trim().toLowerCase(); if (!q) return false;
    const key = Object.keys(byRef).find(k => k.toLowerCase().replace(/_/g, '').includes(q.replace(/_/g, '')));
    if (!key) return false; const l = byRef[key]; map.fitBounds(l.getBounds().pad(2)); l.fire('click'); return true;
  }
  return { map, info, draw, find, get drawing() { return drawing; }, clearSelection() { if (selected) selected.layer.setStyle(selected.style); selected = null; }, destroy() { map.remove(); } };
}
