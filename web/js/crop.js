// Crop and biomass (Sentinel-2) and the 5am.earth on-chain registry: the field map of the farm view, the per-field panel with its NDVI
// chart, and the section of a delivered Lease Check. Everything shown comes from the delivered report; nothing is estimated in the browser.
import { h, chip, num, hash, kv, empty } from './core.js';

export const STATUS = {
  dense_canopy: { label: 'Dense canopy', color: '#2f7d3b', kind: 'good' },
  green_canopy: { label: 'Green canopy', color: '#74b05a', kind: 'good' },
  after_peak: { label: 'After peak: harvested or senescing', color: '#d39a1f', kind: 'warn' },
  sparse: { label: 'Sparse vegetation', color: '#b08d57', kind: 'warn' },
  no_crop_signal: { label: 'No crop canopy seen', color: '#c0392b', kind: 'bad' },
  no_clear_view: { label: 'No clear view yet', color: '#8a8f86', kind: '' },
  unavailable: { label: 'Satellite data unavailable', color: '#8a8f86', kind: '' },
};
const NONE = { label: 'Not analysed yet', color: '#5b8fb0', kind: 'info' };
const statusOf = p => (p ? STATUS[p.status?.code] : null) || NONE;
const t1 = v => v == null ? '-' : Number(v).toFixed(1);
const t2 = v => v == null ? '-' : Number(v).toFixed(2);
const pct = v => v == null ? '-' : `${v > 0 ? '+' : ''}${v} %`;
const IPFS = 'https://c-ipfs-gw.nmkr.io/ipfs/';
const GROUP = { c4: 'C4 crop', c3_cereal: 'C3 cereal', other: 'Other crop', unknown: 'Crop not stated' };

// ---------------------------------------------------------------- map
export function fieldMap(el, { boundaries, section, onSelect }) {
  const L = window.L;
  const map = L.map(el, { zoomControl: true, attributionControl: true });
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Esri World Imagery' }).addTo(map);
  const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' });
  L.control.layers({ 'Satellite': sat, 'Street map': osm, 'No tiles (offline)': L.layerGroup() }, {}, { collapsed: true }).addTo(map);
  let byId = new Map(), selected = null;
  const style = pid => { const s = statusOf(byId.get(pid)); return { color: pid === selected ? '#ffffff' : s.color, weight: pid === selected ? 4 : 2, fillColor: s.color, fillOpacity: .45 }; };
  const layers = new Map();
  const gj = L.geoJSON(boundaries, {
    style: f => style(f.properties.parcel_id),
    onEachFeature: (f, lyr) => { layers.set(f.properties.parcel_id, lyr); lyr.bindTooltip(f.properties.parcel_id, { direction: 'top', sticky: true }); lyr.on('click', () => api.select(f.properties.parcel_id)); },
  }).addTo(map);
  const fit = () => map.fitBounds(gj.getBounds().pad(.35), { maxZoom: 18 });
  fit();
  const api = {
    map,
    setSection(sec) { byId = new Map((sec?.parcels || []).map(p => [p.parcel_id, p])); for (const [pid, lyr] of layers) lyr.setStyle(style(pid)); },
    select(pid) { selected = pid; for (const [k, lyr] of layers) lyr.setStyle(style(k)); layers.get(pid)?.bringToFront(); onSelect(pid); },
    destroy() { map.remove(); },
  };
  api.setSection(section);
  setTimeout(() => { map.invalidateSize(); fit(); }, 60);  // the view is built before it is attached to the page
  return api;
}

export function legend() {
  return h('div', { class: 'legend small' }, Object.entries(STATUS).filter(([k]) => k !== 'unavailable').concat([['none', NONE]]).map(([, s]) => h('span', null, h('i', { style: `background:${s.color}` }), s.label)));
}

// ---------------------------------------------------------------- NDVI chart (inline SVG, no library)
const NS = 'http://www.w3.org/2000/svg';
function svg(tag, attrs, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  for (const k of kids.flat()) if (k != null) el.append(k.nodeType ? k : document.createTextNode(String(k)));
  return el;
}
const plusYear = d => { const [y, m, day] = d.split('-'); return `${Number(y) + 1}-${m}-${day === '29' && m === '02' ? '28' : day}`; };

export function ndviChart(p, section) {
  const W = 640, H = 220, L = 38, R = 12, T = 12, B = 28;
  const s0 = Date.parse(section.season.start), s1 = Date.parse(section.season.end), span = Math.max(1, s1 - s0);
  const x = d => L + (Date.parse(d) - s0) / span * (W - L - R);
  const y = v => T + (1 - Math.max(0, Math.min(1, v))) * (H - T - B);
  const g = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'ndvi', role: 'img', 'aria-label': `NDVI of ${p.parcel_id} this season and the same weeks last year` });
  for (const v of [0, .2, .4, .6, .8, 1]) g.append(svg('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'grid' }), svg('text', { x: L - 6, y: y(v) + 4, class: 'ax', 'text-anchor': 'end' }, v.toFixed(1)));
  const start = new Date(s0);
  for (let d = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + (start.getUTCDate() > 1 ? 1 : 0), 1)); d.getTime() <= s1; d.setUTCMonth(d.getUTCMonth() + 1)) {
    const iso = d.toISOString().slice(0, 10);
    g.append(svg('line', { x1: x(iso), x2: x(iso), y1: T, y2: H - B, class: 'grid v' }), svg('text', { x: x(iso) + 3, y: H - B + 16, class: 'ax' }, d.toLocaleString('en', { month: 'short', timeZone: 'UTC' })));
  }
  const m = p.metrics?.season;
  if (m?.baseline_ndvi != null) g.append(svg('line', { x1: L, x2: W - R, y1: y(m.baseline_ndvi + .1), y2: y(m.baseline_ndvi + .1), class: 'soil' }), svg('text', { x: W - R - 2, y: y(m.baseline_ndvi + .1) - 4, class: 'ax', 'text-anchor': 'end' }, 'soil level'));
  const line = (obs, map, cls) => { if (obs.length > 1) g.append(svg('polyline', { points: obs.map(o => `${map(o.date).toFixed(1)},${y(o.ndvi).toFixed(1)}`).join(' '), class: cls })); };
  const prev = (p.observations?.previous || []).map(o => ({ ...o, date: plusYear(o.date) }));
  line(prev, x, 'prev');
  line(p.observations?.season || [], x, 'cur');
  for (const o of p.observations?.season || []) g.append(svg('circle', { cx: x(o.date), cy: y(o.ndvi), r: 3.5, class: 'pt' }, svg('title', null, `${o.date}: NDVI ${o.ndvi.toFixed(2)} (10th-90th percentile ${o.ndvi_p10.toFixed(2)}-${o.ndvi_p90.toFixed(2)}, ${o.clear_px} clear pixels)\n${o.item}`)));
  for (const o of prev) g.append(svg('circle', { cx: x(o.date), cy: y(o.ndvi), r: 2.5, class: 'pt prev' }, svg('title', null, `last year ${o.date.replace(/^\d{4}/, y0 => String(Number(y0) - 1))}: NDVI ${o.ndvi.toFixed(2)}`)));
  return h('figure', { class: 'chart' }, g, h('figcaption', { class: 'small muted' }, h('span', { class: 'key cur' }), 'this season (clear Sentinel-2 views)  ', h('span', { class: 'key prev' }), 'same weeks last year  ', h('span', { class: 'key soil' }), 'soil level used for biomass'));
}

// ---------------------------------------------------------------- one field
export function registryCard(r) {
  if (!r) return h('div', { class: 'small muted' }, 'No 5am.earth registration is linked to this parcel.');
  if (r.status !== 'checked') return h('div', { class: 'callout warn small' }, h('b', null, '5am.earth registry: '), r.status === 'unavailable' ? `lookup did not answer (${r.reason || 'unavailable'}). Nothing is claimed.` : 'not checked on this server.', r.tx_hash && h('div', null, hash(r.tx_hash)));
  const ok = r.verified && r.boundary_matches_registry;
  return h('div', { class: 'registry ' + (ok ? 'ok' : 'bad') },
    h('div', { class: 'row between' }, h('b', null, 'On-chain record · 5am.earth Project Swaminathan'), chip(r.verified ? '✓ verified on Cardano mainnet' : '✗ not verified', r.verified ? 'good' : 'bad')),
    kv([
      ['Transaction', h('a', { href: r.explorer, target: '_blank', rel: 'noopener' }, r.tx_hash.slice(0, 16) + '…' + r.tx_hash.slice(-6))],
      ['Registered', r.block_time ? new Date(r.block_time * 1000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC' : '-'],
      ['Farm id · field agent', `${r.farm_id} · ${r.agent_code}`],
      ['Registered area', `${num(r.registered_area_m2, 0)} m² (${num(r.registered_area_m2 / 4046.8564224, 2)} acre)`],
      ['Boundary document (IPFS)', h('span', null, h('a', { href: IPFS + r.document_cid, target: '_blank', rel: 'noopener' }, r.document_cid.slice(0, 12) + '…'), ' ', r.document?.cid_verified ? chip('content hash ✓', 'good') : chip('hash not checked', 'warn'))],
      ['Boundary used here', r.boundary_matches_registry ? chip('identical to the registered one', 'good') : chip('differs from the registered one', 'bad')],
      ['value_2 (raw datum field)', h('span', { title: r.value_2_note }, `${r.value_2} · meaning not documented`)],
    ]),
    h('div', { class: 'small muted' }, (r.limits || []).join(' ')));
}

export function fieldDetail(p, section, meta) {
  if (!p) return empty('Click a field on the map.');
  const s = statusOf(p), unit = meta?.area_unit || p.boundary?.unit || '';
  const lease = p.contract_id ? `${p.contract_id} · ${p.owner} · ${num(p.area_contract)} ${unit} under lease` : 'No lease row';
  const head = h('div', { class: 'stack tight' },
    h('div', { class: 'row between' }, h('h3', null, p.parcel_id), chip(s.label, s.kind)),
    h('div', { class: 'small muted' }, `${p.farmed ? `Farmed field ${p.field_id}: ${p.crop || 'crop not stated'}` : 'Not on your list of farmed fields'} · ${lease}`),
    h('div', { class: 'small muted' }, `Boundary ${num(p.boundary.area)} ${unit} (${num(p.boundary.area_m2, 0)} m²) from ${p.boundary.source === '5am.earth' ? 'the 5am.earth registration' : 'your upload'}`));
  if (!p.observations) return h('div', { class: 'stack' }, head, h('div', { class: 'callout' }, p.status?.text || 'Satellite data unavailable for this report.'), registryCard(p.registry));
  const m = p.metrics.season, b = p.biomass.season, bp = p.biomass.previous;
  return h('div', { class: 'stack' }, head,
    h('p', { class: 'status-text' }, p.status.text),
    h('div', { class: 'tiles' },
      h('div', { class: 'tile' }, h('div', { class: 'n' }, t2(m.latest_ndvi)), h('div', { class: 'l' }, `NDVI now (${m.latest_date || '-'})`)),
      h('div', { class: 'tile' }, h('div', { class: 'n' }, t2(m.peak_ndvi)), h('div', { class: 'l' }, `Season peak (${m.peak_date || '-'})`)),
      h('div', { class: 'tile good' }, h('div', { class: 'n' }, b.t_per_ha == null ? '-' : `${t1(b.t_per_ha)} t/ha`), h('div', { class: 'l' }, b.t_per_ha == null ? (b.reason || 'not estimated') : `Season biomass, estimate ${t1(b.low)}-${t1(b.high)} · ${t2(p.biomass.field_t)} t on this field`)),
      h('div', { class: 'tile ' + ((p.biomass.change_pct ?? 0) < -30 ? 'warn' : '') }, h('div', { class: 'n' }, pct(p.biomass.change_pct)),
        h('div', { class: 'l' }, bp.t_per_ha == null ? 'vs. same weeks last year (no estimate)' : p.biomass.change_pct == null ? `vs. last year: only ${t1(bp.t_per_ha)} t/ha then, too little to compare` : `vs. same weeks last year (${t1(bp.t_per_ha)} t/ha)`))),
    ndviChart(p, section),
    h('div', { class: 'small muted' }, `${m.clear_observations || 0} clear views this season (${p.dates.season.cloudy} cloudy, ${p.dates.season.no_data} without data); longest gap ${m.max_gap_days ?? '-'} days. `,
      `${p.observations.season[0]?.px ?? '-'} pixels of 10 m (${p.pixel_rule}). ${GROUP[p.crop_group] || p.crop_group}: light-use efficiency ${b.lue_g_per_mj ?? '-'} g per MJ.`),
    p.flags.length ? h('div', { class: 'callout warn' }, h('b', null, 'Worth a look'), h('ul', null, p.flags.map(f => h('li', null, f.text)))) : null,
    registryCard(p.registry));
}

// ---------------------------------------------------------------- section of the delivered report
export function cropSection(rep) {
  const sec = rep.crop_monitoring;
  if (!sec) return null;
  const unit = rep.meta.area_unit, sum = sec.summary;
  const box = h('div', { class: 'stack' });
  const head = h('div', null, h('h4', null, `Crop and biomass · ${sec.season.start} to ${sec.season.end}`),
    h('div', { class: 'small muted' }, 'Sentinel-2 satellite (10 m) and the 5am.earth farm registry on Cardano. Observations, not findings about money.'));
  if (sec.status !== 'ok') {
    box.append(head, h('div', { class: 'callout warn' }, sec.unavailable.map(x => h('div', null, x))));
    if (sec.parcels.some(p => p.registry)) box.append(...sec.parcels.filter(p => p.registry).map(p => h('div', null, h('b', null, p.parcel_id), registryCard(p.registry))));
    return box;
  }
  const detail = h('div');
  let open = null;
  const rows = sec.parcels.map(p => {
    const s = statusOf(p), r = p.registry || {};
    const tr = h('tr', { class: 'click', tabindex: 0, onclick: () => toggle(p, tr), onkeydown: e => { if (e.key === 'Enter') toggle(p, tr); } },
      h('td', null, h('span', { class: 'dot', style: `background:${s.color}` }), p.parcel_id), h('td', null, p.farmed ? (p.crop || '-') : h('i', null, 'not farmed')),
      h('td', null, s.label), h('td', null, t2(p.metrics.season.peak_ndvi)),
      h('td', null, p.biomass.season.t_per_ha == null ? '-' : `${t1(p.biomass.season.t_per_ha)} t/ha`), h('td', null, pct(p.biomass.change_pct)),
      h('td', null, r.status === 'checked' ? chip(r.verified && r.boundary_matches_registry ? '✓ on-chain' : '✗ check', r.verified && r.boundary_matches_registry ? 'good' : 'bad') : r.status ? chip(r.status, 'warn') : '-'),
      h('td', null, p.flags.length ? chip(String(p.flags.length), 'warn') : ''));
    return tr;
  });
  function toggle(p, tr) {
    rows.forEach(r => r.classList.remove('sel'));
    if (open === p.parcel_id) { open = null; detail.replaceChildren(); return; }
    open = p.parcel_id; tr.classList.add('sel');
    detail.replaceChildren(h('div', { class: 'card inset' }, fieldDetail(p, sec, rep.meta)));
  }
  const flags = sec.parcels.flatMap(p => p.flags);
  box.append(head,
    h('div', { class: 'tiles' },
      h('div', { class: 'tile' }, h('div', { class: 'n' }, `${sum.parcels_observed}/${sum.parcels_with_boundary}`), h('div', { class: 'l' }, 'Fields seen by the satellite')),
      h('div', { class: 'tile good' }, h('div', { class: 'n' }, sum.season_biomass_t_total == null ? '-' : `${t1(sum.season_biomass_t_total)} t`), h('div', { class: 'l' }, 'Season biomass, all fields (estimate)')),
      h('div', { class: 'tile ' + (flags.length ? 'warn' : '') }, h('div', { class: 'n' }, flags.length), h('div', { class: 'l' }, 'Observations worth a look')),
      h('div', { class: 'tile info' }, h('div', { class: 'n' }, `${sum.registry_verified}/${sum.registry_linked}`), h('div', { class: 'l' }, 'Boundaries verified on Cardano (5am.earth)'))),
    h('table', { class: 't' }, h('thead', null, h('tr', null, ['Field', 'Crop (your list)', 'Canopy now', 'Peak NDVI', 'Season biomass', 'vs. last year', '5am.earth', ''].map(x => h('th', null, x)))), h('tbody', null, rows)),
    h('div', { class: 'small muted' }, 'Click a row for the NDVI curve, the biomass estimate and the on-chain record.'), detail,
    flags.length ? h('div', { class: 'callout warn' }, h('b', null, 'Worth a look'), h('ul', null, flags.map(f => h('li', null, f.text)))) : null,
    h('details', null, h('summary', null, 'How this is computed'), h('ul', { class: 'small' }, Object.entries(sec.method).filter(([k]) => k !== 'version').map(([k, v]) => h('li', null, h('b', null, k + ': '), v))),
      h('div', { class: 'small muted' }, sec.sources.join(' · '), ` · ${sec.method.version}`)));
  return box;
}
