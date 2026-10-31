import { api, ws, h, chip, fmtTime, num, money, toast, guard, download, copy, hash, kv, field, empty, spinner, ApiError } from './core.js';
import { parcelMap } from './map.js';
import { orderPanel, stateChip } from './order.js';
import { fieldMap, fieldDetail, legend } from './crop.js';

export const ctx = { config: null, rerender: () => {} };
const country = () => ws.current?.country;
const ROLE_TEXT = { owner: 'Landowner', farm: 'Tenant farm', developer: 'Energy developer' };
const need = role => { const w = ws.current; if (!w) return h('div', { class: 'card empty' }, 'Create a workspace first. ', h('a', { href: '#/start' }, 'Get started')); if (role && w.role !== role) return h('div', { class: 'card' }, h('h3', null, `This area is for ${ROLE_TEXT[role]} workspaces`), h('p', null, `You are signed in as ${ROLE_TEXT[w.role]} (${w.name}). Each role has its own entry; create or switch workspace to use another.`), h('a', { class: 'btn primary', href: '#/start' }, 'Switch or create workspace')); return null; };
const priceOf = svc => ctx.config.services[svc].price.display;

// ---------------------------------------------------------------- start / workspaces
export function start(q) {
  const role = q.get('role') || 'owner';
  const name = h('input', { placeholder: 'Your name or company', maxlength: 80, value: '' });
  const r = h('select', null, ['owner', 'farm', 'developer'].map(x => h('option', { value: x, selected: x === role }, ROLE_TEXT[x])));
  const c = h('select', null, h('option', { value: 'DE' }, 'Germany'), h('option', { value: 'IN' }, 'India'));
  const list = ws.read().list;
  return h('div', { class: 'cols' },
    h('div', { class: 'card' }, h('h2', null, 'Create a workspace'),
      h('p', { class: 'muted' }, 'A workspace keeps your parcels, documents, orders and deals private to you. There is no password: your browser keeps a secret token, so do not clear site data if you want to come back.'),
      field('Name', name), field('I am a…', r), field('Country', c, 'Data, units, currency and documents follow the country.'),
      h('button', { class: 'btn primary', onclick: e => guard(async () => { const res = await api('/session', { method: 'POST', body: { name: name.value, role: r.value, country: c.value } }); ws.add(res.user, res.token); location.hash = '#/' + (res.user.role === 'owner' ? 'owner' : res.user.role === 'farm' ? 'farm' : 'developer'); ctx.rerender(); }, e.target) }, 'Create workspace')),
    h('div', { class: 'card' }, h('h2', null, 'Your workspaces on this device'), list.length ? h('div', { class: 'list' }, list.map(w => h('div', { class: 'item' + (w.id === ws.current?.id ? ' sel' : '') },
      h('div', { class: 't' }, h('b', null, w.name), h('span', { class: 'small muted' }, `${ROLE_TEXT[w.role]} · ${w.country}${w.persona ? ' · demo' : ''}`)),
      h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => { ws.use(w.id); ctx.rerender(); location.hash = '#/'; } }, 'Use'), h('button', { class: 'btn sm danger', onclick: () => { if (confirm('Forget this workspace on this device? Its data stays on the server but you lose access without the token.')) { ws.drop(w.id); ctx.rerender(); } } }, 'Forget'))))) : empty('None yet.'),
      h('p', { class: 'small muted' }, 'Two-party flows (pool deals) need two workspaces: yours, and a clearly labelled demo counterpart that you can create inside the Developer area.')));
}

// ---------------------------------------------------------------- home
export function home() {
  const w = ws.current;
  const route = txt => { const s = txt.toLowerCase();
    if (/lease|rent|farm|contract|pacht/.test(s)) return '#/farm';
    if (/neighbo|nda|pool|developer|wind|solar|site|audit/.test(s)) return '#/developer';
    if (/map|explore/.test(s)) return '#/map';
    return '#/owner'; };
  const agents = { owner: ['Land Audit', 'owner'], farm: ['Lease Check', 'farm'], developer: ['Pool Access & Audit', 'developer'] };
  const text = h('input', { placeholder: 'Describe what you need, e.g. "check my leases" or "audit a solar site" - we open the right workflow', 'aria-label': 'What would you like to check?' });
  const sel = h('select', { 'aria-label': 'Agent' }, h('option', { value: '' }, 'Pick for me'), Object.entries(agents).map(([r, [n]]) => h('option', { value: r, selected: w?.role === r }, n)));
  const go = () => { const r = sel.value || null; const dest = r ? '#/' + r : route(text.value); location.hash = w ? (r && w.role !== r ? '#/start?role=' + r : dest) : '#/start?role=' + (r || dest.slice(2) || 'owner'); };
  text.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  const chips = [['Check my parcel', () => location.hash = w?.role === 'owner' ? '#/owner' : '#/start?role=owner'], ['Check my leases', () => location.hash = w?.role === 'farm' ? '#/farm' : '#/start?role=farm'], ['Audit a site', () => location.hash = w?.role === 'developer' ? '#/developer' : '#/start?role=developer'],
    ['Show me the map', () => location.hash = '#/map'], ['What data do you use?', () => document.getElementById('coverage')?.scrollIntoView({ behavior: 'smooth' })]];
  const cards = [['owner', 'Landowner', 'Audit a parcel, attach documents, publish only when you decide.', ['land_audit']], ['farm', 'Tenant farm', 'Find paid-but-unfarmed land, area mismatches, expensive rents and deadlines.', ['lease_check']], ['developer', 'Energy developer', 'Audit sites, meet neighbouring projects under NDA, get a joint calculation.', ['land_audit', 'pool_access']]];
  return h('div', { class: 'home' },
    h('div', { class: 'hero' }, h('div', { class: 'hero-mark' }, 'A'), h('h2', null, 'What would you like to check?'),
      h('div', { class: 'composer' }, text, h('div', { class: 'composer-row' }, h('span', { class: 'agent-pick' }, h('span', { class: 'agent-dot' }, 'A'), sel), h('a', { class: 'pick-map', href: '#/map' }, '📍 Pick on map'), h('span', { class: 'grow' }), h('button', { class: 'send', 'aria-label': 'Go', onclick: go }, '↑'))),
      h('div', { class: 'chips' }, chips.map(([l, f]) => h('button', { class: 'chip-btn', onclick: f }, l))),
      !w && h('p', { class: 'small muted' }, 'You will be asked to create a workspace first (ten seconds, no password).')),
    h('div', { class: 'tiles' }, cards.map(([role, title, text2, svcs]) => h('div', { class: 'card stack' }, h('h3', null, title), h('p', { class: 'muted' }, text2),
      h('div', { class: 'small' }, svcs.map(s => h('div', null, ctx.config.services[s].title, ' · ', h('b', null, priceOf(s))))),
      h('a', { class: 'btn primary', href: w && w.role === role ? '#/' + role : `#/start?role=${role}` }, w && w.role === role ? 'Open' : 'Start as ' + title.toLowerCase())))),
    h('div', { class: 'card' }, h('h3', null, 'Agents in AgroLand'), h('table', { class: 't' }, h('thead', null, h('tr', null, ['#', 'Agent', 'What you get', 'Price', 'Countries'].map(x => h('th', null, x)))),
      h('tbody', null, Object.entries(ctx.config.services).map(([k, s]) => h('tr', null, h('td', null, 'Agent ' + s.agent), h('td', null, h('b', null, s.title)), h('td', null, s.summary), h('td', null, s.price.display), h('td', null, s.countries.join(' · ')))))),
      h('p', { class: 'small muted' }, 'The same agents answer here and inside Sokosumi. Prices are identical in both places.')),
    h('div', { class: 'card', id: 'coverage' }, h('h3', null, 'Data and sources'), h('div', { class: 'cols' }, Object.entries(ctx.config.coverage).map(([k, c]) => h('div', null, h('b', null, c.name), h('ul', { class: 'small muted' }, c.notes.map(n => h('li', null, n))))))));
}

// ---------------------------------------------------------------- shared: parcel picker
async function parcelPicker({ onSaved, allowDraw = true, saved, leased = [] }) {
  const w = ws.current, root = h('div', { class: 'stack' });
  const mapEl = h('div', { class: 'map' }); let picked = null;
  const pickedBox = h('div', { class: 'small muted' }, 'Click a parcel on the map' + (allowDraw ? ', or draw your own outline.' : '.'));
  const saveBtn = h('button', { class: 'btn primary', disabled: true, onclick: e => guard(async () => { const p = await api('/parcels', { method: 'POST', body: picked.body }); toast('Saved to your parcels'); onSaved(p); }, e.target) }, 'Use this parcel');
  const m = await parcelMap(mapEl, { country: w.country, saved, leased, onSelect: p => { picked = { body: { source: p.source, ref: p.ref }, label: p.label }; pickedBox.replaceChildren(h('b', null, p.label), ` · ${num(p.area_ha)} ha`, p.signal ? h('span', null, ' · signal ', h('span', { class: 'sig ' + p.signal }), p.signal) : '', p.demo ? chip(' demo', 'info') : ''); saveBtn.disabled = false; } });
  let drawCtl = null; const drawBtn = h('button', { class: 'btn', onclick: () => {
    if (drawCtl) { drawCtl.finish(); return; }
    drawBtn.textContent = 'Finish outline'; drawCtl = m.draw(async geom => { drawBtn.textContent = 'Draw my own outline'; drawCtl = null;
      const label = prompt('Name this site', 'My site'); if (label == null) return;
      await guard(async () => { const p = await api('/parcels', { method: 'POST', body: { source: 'drawn', geometry: geom, label } }); toast('Outline saved'); onSaved(p); }); });
  } }, 'Draw my own outline');
  root.append(mapEl, m.info, pickedBox, h('div', { class: 'row' }, saveBtn, allowDraw && drawBtn));
  return root;
}

function parcelList(parcels, selId, onPick, onDelete) {
  if (!parcels.length) return empty('No parcels yet. Pick one on the map.');
  return h('div', { class: 'list' }, parcels.map(p => h('div', { class: 'item' + (p.id === selId ? ' sel' : '') },
    h('div', { class: 't' }, h('b', null, p.label), h('span', { class: 'small muted' }, `${num(p.area_ha)} ha · ${p.source}${p.demo ? ' · demo' : ''} · ownership not verified`)),
    h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => onPick(p) }, p.id === selId ? 'Selected' : 'Select'), onDelete && h('button', { class: 'btn sm danger', onclick: () => onDelete(p) }, '×')))));
}

async function latestOrders(service) { return (await api('/orders')).filter(o => o.service === service); }

function auditComposer(parcel, { onOrder, typeChoices = ['solar', 'wind', 'hybrid'] }) {
  const t = h('select', null, typeChoices.map(x => h('option', { value: x }, x[0].toUpperCase() + x.slice(1))));
  const survey = country() === 'IN' ? h('input', { placeholder: 'Survey number (optional, not verified)' }) : null;
  return h('div', { class: 'stack' }, field('Project type', t), survey && field('Land-record reference', survey, 'Format check only. No state registry offers a public lookup, so it is never verified.'),
    h('div', { class: 'row between' }, h('div', null, 'Land Audit · ', h('b', null, priceOf('land_audit')), h('div', { class: 'small muted' }, 'Price is fixed before you pay.')),
      h('button', { class: 'btn primary', onclick: e => guard(async () => { const o = await api('/orders', { method: 'POST', body: { service: 'land_audit', input: { parcel_id: parcel.id, project_type: t.value, ...(survey?.value ? { survey_number: survey.value } : {}) }, idempotency_key: crypto.randomUUID() } }); onOrder(o); }, e.target) }, 'Review order')));
}

// ---------------------------------------------------------------- owner
export async function owner(q = new URLSearchParams()) {
  const blocked = need('owner'); if (blocked) return blocked;
  const root = h('div', { class: 'stack' }); let parcels = await api('/parcels'), sel = null, orderBox = h('div', null, empty('Order an audit to see it here.')), tab = q.get('tab') === 'listings' ? 'listings' : 'audit';
  const listings = await api('/listings');
  async function draw() {
    parcels = await api('/parcels');
    const tabs = h('div', { class: 'tabs' }, [['audit', 'Audit a parcel'], ['listings', `My listings (${listings.length})`]].map(([k, l]) => h('button', { class: tab === k ? 'on' : '', onclick: () => { tab = k; draw(); } }, l)));
    const body = h('div');
    if (tab === 'audit') {
      const mapCol = await parcelPicker({ saved: parcels, onSaved: p => { sel = p; draw(); } });
      body.append(h('div', { class: 'cols wide-r' }, h('div', { class: 'card stack' }, h('h3', null, '1 · Choose the parcel'), mapCol, h('h4', null, 'Your parcels'), parcelList(parcels, sel?.id, p => { sel = p; draw(); }, async p => { await guard(() => api('/parcels/' + p.id, { method: 'DELETE' })); if (sel?.id === p.id) sel = null; draw(); })),
        h('div', { class: 'stack' }, h('div', { class: 'card stack' }, h('h3', null, '2 · Audit'), sel ? [h('div', null, h('b', null, sel.label)), auditComposer(sel, { onOrder: o => { orderBox.replaceChildren(orderPanel(o, { onChange: () => {} })); orderBox.scrollIntoView({ behavior: 'smooth' }); } })] : empty('Select a parcel first.')),
          h('div', { class: 'card stack' }, h('h3', null, '3 · Result and listing'), orderBox, sel && listingForm(sel, draw)))));
      const prior = sel ? (await latestOrders('land_audit')).find(o => o.subject === sel.label) : null;
      if (prior && orderBox.querySelector('.empty')) orderBox.replaceChildren(orderPanel(prior));
    } else {
      body.append(listings.length ? h('div', { class: 'stack' }, (await api('/listings')).map(listingCard)) : empty('No listings yet. Audit a parcel and publish it when you are ready.'));
    }
    root.replaceChildren(h('div', { class: 'callout' }, 'Publishing does not transfer rights to your land. Ownership is never verified by AgroLand; your document stays private to you.'), tabs, body);
  }
  function listingCard(l) {
    const statusKind = { published: 'good', needs_audit: 'warn', private: '' }[l.status];
    return h('div', { class: 'card stack' }, h('div', { class: 'row between' }, h('b', null, l.parcel.label), chip(l.status.replace('_', ' '), statusKind)),
      h('div', { class: 'small muted' }, `${l.deal_type} · ${l.price} · ${num(l.parcel.area_ha)} ha · consent ${l.consent ? 'on' : 'off'}`),
      l.audit ? h('div', null, `Attached audit: ${l.audit.verdict} ${l.audit.score}/100`, l.audit.data_complete ? '' : ' (data incomplete)') : h('div', { class: 'callout warn' }, 'Not visible to developers yet: attach a delivered audit (run one in the Audit tab, then attach it here).'),
      h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: e => guard(async () => { await api('/listings/' + l.id, { method: 'PATCH', body: { consent: !l.consent } }); toast(l.consent ? 'Withdrawn from developers' : 'Published'); location.reload(); }, e.target) }, l.consent ? 'Withdraw consent' : 'Publish'),
        !l.audit && h('button', { class: 'btn sm', onclick: e => guard(async () => { const o = (await latestOrders('land_audit')).find(o => o.state === 'delivered' && o.subject === l.parcel.label); if (!o) throw new Error('No delivered audit for this parcel yet.'); await api('/listings/' + l.id, { method: 'PATCH', body: { audit_order_id: o.id } }); location.reload(); }, e.target) }, 'Attach latest audit'),
        h('button', { class: 'btn sm danger', onclick: e => guard(async () => { if (confirm('Delete this listing?')) { await api('/listings/' + l.id, { method: 'DELETE' }); location.reload(); } }, e.target) }, 'Delete')),
      l.interests.length ? h('div', null, h('h4', null, 'Interested developers'), h('div', { class: 'list' }, l.interests.map(i => h('div', { class: 'item' }, h('div', { class: 't' }, h('b', null, i.developer_name), h('span', { class: 'small muted' }, i.message || '')),
        i.status === 'pending' ? h('div', { class: 'row' }, ['accepted', 'declined'].map(d => h('button', { class: 'btn sm', onclick: e => guard(async () => { await api(`/listings/${l.id}/interests/${i.id}`, { method: 'POST', body: { decision: d } }); location.reload(); }, e.target) }, d === 'accepted' ? 'Share boundary' : 'Decline'))) : chip(i.status, i.status === 'accepted' ? 'good' : ''))))) : null);
  }
  await draw(); return root;
}

function listingForm(parcel, redraw) {
  const doc = { id: null }, docInfo = h('div', { class: 'small muted' }, 'No document attached.');
  const file = h('input', { type: 'file', accept: 'application/pdf', onchange: e => guard(async () => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f); const d = await api('/documents', { method: 'POST', form: fd }); doc.id = d.id; docInfo.textContent = `Attached ${d.filename} (private; owner-declared, not verified)`; }) });
  const sample = h('button', { class: 'btn sm', onclick: e => guard(async () => { const d = await api('/documents/sample', { method: 'POST', body: { label: parcel.label } }); doc.id = d.id; docInfo.textContent = 'Attached a clearly marked SAMPLE document.'; }, e.target) }, 'Use a marked sample');
  const type = h('select', null, h('option', { value: 'lease' }, 'Lease'), h('option', { value: 'sale' }, 'Sale'));
  const price = h('input', { type: 'number', min: 1, step: 'any', placeholder: country() === 'DE' ? 'EUR per ha per year (lease) or total (sale)' : 'INR per acre per year (lease) or total (sale)' });
  const consent = h('input', { type: 'checkbox' });
  return h('details', { open: true }, h('summary', null, 'List this parcel'), h('div', { class: 'stack', style: 'margin-top:.6rem' }, field('Document (PDF, private)', file), h('div', { class: 'row' }, sample, docInfo), field('Offer', type), field('Price', price),
    h('label', { class: 'check' }, consent, h('span', null, 'I agree that developers may see the allow-listed summary (area, region, price, audit result). My name, document and exact boundary stay hidden until I accept a specific developer.')),
    h('button', { class: 'btn primary', onclick: e => guard(async () => {
      const audit = (await latestOrders('land_audit')).find(o => o.state === 'delivered' && o.subject === parcel.label);
      await api('/listings', { method: 'POST', body: { parcel_id: parcel.id, deal_type: type.value, price: Number(price.value), consent: consent.checked, document_id: doc.id, audit_order_id: audit?.id } });
      toast(audit ? 'Listing saved' : 'Listing saved - attach a delivered audit to make it visible'); redraw(); }, e.target) }, 'Save listing')));
}

// ---------------------------------------------------------------- farm
export async function farm() {
  const blocked = need('farm'); if (blocked) return blocked;
  const root = h('div', { class: 'stack' }), orderBox = h('div', null, empty('Review the order to start. Results stay here after a refresh.'));
  const [ds, demos] = await Promise.all([api('/farm/dataset'), api('/farm/demos')]);
  const showcase = demos.find(d => d.registry_linked) || demos[0];
  let source = ds.saved ? 'saved' : 'demo:' + showcase.id;
  let demo = await api('/farm/demo?demo=' + encodeURIComponent(source.startsWith('demo:') ? source.slice(5) : showcase.id));
  const dataset = () => source === 'saved' ? ds.dataset : demo;
  const files = { contracts_csv: '', cadastre_csv: '', fields_csv: '', boundaries_geojson: '' };
  const inputs = {};
  const fileIn = (key, label, hint, accept = '.csv,text/csv') => field(label, inputs[key] = h('input', { type: 'file', accept, onchange: async e => { files[key] = await e.target.files[0]?.text() || ''; } }), hint);
  // Test data for demos/videos: fill the upload fields from the selected demonstration farm, exactly as if the files had been chosen from disk.
  const fileText = k => k === 'boundaries_geojson' ? (demo.boundaries?.features?.length ? JSON.stringify(demo.boundaries) : '') : (() => { const rows = { contracts_csv: demo.contracts, cadastre_csv: demo.cadastre, fields_csv: demo.fields }[k], cols = COLS[k]; return [cols.join(','), ...rows.map(r => cols.map(c => r[c] ?? '').join(','))].join('\n'); })();
  const FILENAME = { contracts_csv: 'contracts.csv', cadastre_csv: 'cadastre.csv', fields_csv: 'fields.csv', boundaries_geojson: 'boundaries.geojson' };
  const loadTestFiles = () => { for (const k of Object.keys(inputs)) { const text = fileText(k); if (!text) continue; const dt = new DataTransfer(); dt.items.add(new File([text], FILENAME[k])); inputs[k].files = dt.files; files[k] = text; } toast('Test files loaded into the upload fields. Press "Validate and save".'); };
  const downloadTestFiles = () => { for (const k of Object.keys(FILENAME)) { const text = fileText(k); if (text) download(new Blob([text], { type: k.endsWith('geojson') ? 'application/geo+json' : 'text/csv' }), FILENAME[k]); } };
  const info = h('div', { class: 'small muted' });
  function describe() {
    const d = dataset(), s = d.settings, b = d.boundaries?.features || [];
    info.replaceChildren(...[source === 'saved' ? `Saved data: ${ds.label} (${d.contracts.length} leases), updated ${fmtTime(ds.updated_at)}.` : `Labelled demonstration farm: ${s.farm_name}, ${s.region}. ${d.contracts.length} leases, ${s.currency} and ${s.area_unit}.`,
      b.length ? h('div', { class: 'row', style: 'margin-top:.35rem' }, chip(`${b.length} field outlines`, 'info'), b.some(f => f.properties.registry) ? chip('outlines registered on Cardano (5am.earth)', 'good') : null) : null].filter(Boolean));
  }
  const srcSel = h('select', { onchange: e => guard(async () => { source = e.target.value; if (source.startsWith('demo:')) demo = await api('/farm/demo?demo=' + encodeURIComponent(source.slice(5))); describe(); await drawFields(); }) },
    demos.map(d => h('option', { value: 'demo:' + d.id, selected: source === 'demo:' + d.id }, `Demo: ${d.farm_name.replace(' (demo)', '')}, ${d.region}${d.registry_linked ? ' · 5am.earth fields' : ''}`)),
    ds.saved && h('option', { value: 'saved', selected: source === 'saved' }, 'My uploaded data'));
  const COLS = { contracts_csv: ['contract_id', 'owner', 'parcel_id', 'area_contract', 'rent_per_unit', 'start_date', 'end_date', 'payment_due'], cadastre_csv: ['parcel_id', 'area_cadastre', 'land_use'], fields_csv: ['field_id', 'parcel_id', 'crop'] };
  const sample = fname => h('a', { href: '#', onclick: e => { e.preventDefault();
    if (fname === 'boundaries') return download(new Blob([JSON.stringify(demo.boundaries || { type: 'FeatureCollection', features: [] }, null, 1)], { type: 'application/geo+json' }), 'boundaries.geojson');
    const rows = { contracts_csv: demo.contracts, cadastre_csv: demo.cadastre, fields_csv: demo.fields }[fname], cols = COLS[fname];
    download(new Blob([[cols.join(','), ...rows.map(r => cols.map(c => r[c] ?? '').join(','))].join('\n')], { type: 'text/csv' }), fname.replace('_csv', '') + '.csv'); } }, fname === 'boundaries' ? 'boundaries.geojson' : fname.replace('_csv', '.csv'));
  const inputOf = () => source === 'saved' ? { source: 'saved' } : { source: 'demo', demo: source.slice(5) };
  const run = h('button', { class: 'btn primary', onclick: e => guard(async () => { const o = await api('/orders', { method: 'POST', body: { service: 'lease_check', input: inputOf(), idempotency_key: crypto.randomUUID() } }); show(o); }, e.target) }, 'Review order');

  // ---- 3 · fields: map + panel, coloured by the latest delivered Lease Check of the dataset on screen
  const fieldsCard = h('div', { class: 'card stack' }), panelBox = h('div', { class: 'fieldpanel' });
  let fmap = null, section = null, applied = null, sel = null;
  function panel(pid) {
    sel = pid;
    const d = dataset();
    if (!pid) return panelBox.replaceChildren(empty('Click a field on the map.'));
    const p = section?.parcels.find(x => x.parcel_id === pid);
    if (p) return panelBox.replaceChildren(fieldDetail(p, section, d.settings));
    const c = d.contracts.find(x => x.parcel_id === pid), f = d.fields.find(x => x.parcel_id === pid), reg = d.boundaries.features.find(x => x.properties.parcel_id === pid)?.properties.registry;
    panelBox.replaceChildren(h('div', { class: 'stack' }, h('h3', null, pid),
      kv([['Lease', c ? `${c.contract_id} · ${c.owner}` : 'none'], ['Area under lease', c ? `${num(c.area_contract)} ${d.settings.area_unit}` : '-'], ['Farmed', f ? `${f.field_id}: ${f.crop || 'crop not stated'}` : 'not on your list']]),
      h('div', { class: 'callout' }, 'Run the Lease Check to add the satellite crop status, the season biomass estimate', reg ? ' and the check of this field\'s 5am.earth registration on Cardano.' : '.'),
      reg && h('div', { class: 'small muted' }, 'Linked registration: ', hash(reg.tx_hash))));
  }
  async function applyOrder(o) {
    if (o.state !== 'delivered' || applied === o.id) return;
    applied = o.id;
    const r = await api(`/orders/${o.id}/result`).catch(() => null);
    const sec = r?.report?.crop_monitoring;
    if (sec && r.report.meta.farm_name === dataset().settings.farm_name) { section = sec; fmap?.setSection(sec); panel(sel || sec.parcels.find(p => p.flags.length)?.parcel_id || null); if (sel) fmap?.select(sel); }
  }
  async function drawFields() {
    fmap?.destroy(); fmap = null; section = null; applied = null; sel = null;
    const d = dataset();
    if (!d.boundaries?.features?.length) {
      fieldsCard.replaceChildren(h('h3', null, '3 · Your fields'), h('div', { class: 'callout' }, 'This dataset has no field outlines. Upload a GeoJSON file with a parcel_id on each outline to add satellite crop status, a biomass estimate and, in India, the 5am.earth on-chain check to the Lease Check.'));
      return;
    }
    const mapEl = h('div', { class: 'map' });
    fieldsCard.replaceChildren(h('div', { class: 'row between' }, h('h3', null, '3 · Your fields: crop, biomass, on-chain record'), legend()),
      h('div', { class: 'cols' }, h('div', { class: 'stack tight' }, mapEl, h('div', { class: 'small muted' }, 'Colours come from the latest delivered Lease Check of this farm. Basemap: Esri World Imagery, often older than the Sentinel-2 views in the report.')), panelBox));
    fmap = fieldMap(mapEl, { boundaries: d.boundaries, section: null, onSelect: panel });
    panel(null);
    const prior = (await latestOrders('lease_check')).find(o => o.state === 'delivered' && o.subject.startsWith(d.settings.farm_name));
    if (prior) await applyOrder(prior);
  }
  let hasOrder = false, setCollapsed = () => {};
  function show(o) { hasOrder = true; setCollapsed(true); orderBox.replaceChildren(orderPanel(o, { onChange: ord => applyOrder(ord) })); }

  describe();
  const prior = (await latestOrders('lease_check'))[0]; if (prior) show(prior);
  let autorun = false; try { autorun = sessionStorage.getItem('agl.farm.autorun') === '1'; sessionStorage.removeItem('agl.farm.autorun'); } catch {}
  const st = demo.settings;
  root.append(h('div', { class: 'farm-cols' },
    h('div', { class: 'card stack side-card' }, h('h3', null, '1 · Your data'),
      h('div', { class: 'data-top' },
        h('div', { class: 'stack tight' }, field('Use', srcSel), info),
        h('div', { class: 'stack tight data-run' }, h('div', { class: 'row between' }, h('div', null, 'Lease Check · ', h('b', null, priceOf('lease_check'))), run),
          h('div', { class: 'small muted' }, 'Your farm data is private to your workspace and is never published. A finding is a statement about your own documents, not about the validity of a lease.'))),
      h('details', { open: true }, h('summary', null, 'Upload my own files'), h('div', { class: 'stack', style: 'margin-top:.7rem' },
        h('p', { class: 'small muted', style: 'margin:0' }, 'Same columns as the demonstration files: ', sample('contracts_csv'), ', ', sample('cadastre_csv'), ', ', sample('fields_csv'), `. Area is in ${st.area_unit}, rent in ${st.currency} per ${st.area_unit} per year. The official record (${st.record_name}) is the cadastre file. `,
          h('span', { class: 'testdata' }, 'Need sample files? ', h('a', { href: '#', onclick: e => { e.preventDefault(); downloadTestFiles(); } }, 'download the test set'), ' or ', h('a', { href: '#', onclick: e => { e.preventDefault(); loadTestFiles(); } }, 'fill the fields below'), '.')),
        h('div', { class: 'file-grid' }, fileIn('contracts_csv', 'Contracts'), fileIn('cadastre_csv', 'Official parcel record'), fileIn('fields_csv', 'Fields you farm'),
          fileIn('boundaries_geojson', 'Field outlines (optional)', null, '.geojson,.json,application/geo+json,application/json')),
        h('p', { class: 'small muted', style: 'margin:0' }, 'Outlines: GeoJSON polygons with a parcel_id each, like ', sample('boundaries'), '. They add the satellite crop status and biomass section (and, in India, a 5am.earth registration via registry.tx_hash).'),
        h('div', null, h('button', { class: 'btn', onclick: e => guard(async () => { await api('/farm/dataset', { method: 'PUT', body: files }); toast('Saved. Running the Lease Check on your uploaded data…'); try { sessionStorage.setItem('agl.farm.autorun', '1'); } catch {} location.reload(); }, e.target) }, 'Validate and save'))))),
    h('div', { class: 'card stack' }, h('h3', null, '2 · Report and reminders'), orderBox)),
  fieldsCard);
  // Once an order exists the data card folds into a slim summary bar (and back with "Change data"), so the report gets the full width.
  const grid = root.firstChild, dataCard = grid.firstChild;
  const summary = h('div', { class: 'data-summary', hidden: true }, h('span', { class: 'ok' }, '✓'), h('b', null, '1 · Your data'), h('span', { class: 'muted ds-text' }), h('span', { class: 'grow' }), h('button', { class: 'btn sm', onclick: () => setCollapsed(false) }, 'Change data'));
  const fold = h('button', { class: 'btn sm ghost fold', onclick: () => setCollapsed(true) }, 'Collapse ↑');
  dataCard.querySelector('h3').after(fold);
  root.prepend(summary);
  setCollapsed = c => {
    grid.classList.toggle('collapsed', c); summary.hidden = !c; fold.hidden = !hasOrder || c;
    if (c) { const d = dataset(); summary.querySelector('.ds-text').textContent = `${d.settings.farm_name} · ${d.contracts.length} leases · ${source === 'saved' ? 'your uploaded files' : 'demo data'}`; }
  };
  setCollapsed(hasOrder);
  await drawFields();
  if (autorun && source === 'saved') run.click();   // after an upload: go straight to the order so the result appears on screen
  return root;
}


// Demo neighbourhood: builds, through the real services, a site of another developer and a Landowner agent's parcel next to our site.
async function neighbourhoodCard(redraw) {
  const root = h('div', { class: 'card stack' });
  let timer = null;
  const ICON = { done: '✓', error: '✗', running: '…', pending: '·' };
  async function render() {
    let job; try { job = await api('/demo/neighbourhood'); } catch { job = { status: 'none', steps: [] }; }
    clearTimeout(timer);
    const start = h('button', { class: 'btn primary', disabled: job.status === 'running', onclick: e => guard(async () => { await api('/demo/neighbourhood', { method: 'POST' }); render(); }, e.target) }, job.status === 'done' ? 'Build again' : job.status === 'running' ? 'Building…' : 'Build demo neighbourhood');
    root.replaceChildren(...[h('div', { class: 'row between' }, h('div', null, h('h3', { style: 'margin:0' }, 'Demo neighbourhood'), h('div', { class: 'small muted' }, 'Puts another developer\'s site and a Landowner agent\'s parcel right next to yours, so you can show how developers find each other and how land is taken on lease. Real matcher, real audits (takes a few minutes); the example parties are labelled demo.')), start),
      job.steps.length ? h('div', { class: 'list' }, job.steps.map(s => h('div', { class: 'item' }, h('div', { class: 't' }, h('b', null, `${ICON[s.status]} ${s.label}`), s.detail ? h('span', { class: 'small muted' }, s.detail) : null), chip(s.status, s.status === 'done' ? 'good' : s.status === 'error' ? 'bad' : s.status === 'running' ? 'info' : '')))) : null,
      job.status === 'done' ? h('div', { class: 'callout good' }, 'Done. 1) ', h('a', { href: '#/developer?tab=deals' }, 'Matches & deals'), ': the other developer\'s anonymous teaser, then consent, payment, NDA and disclosure. 2) ', h('a', { href: '#/developer?tab=market' }, 'Owner listings'), ': take the Landowner agent\'s parcel on lease; it then appears on the map below.') : null,
      job.status === 'error' ? h('div', { class: 'callout bad' }, job.error) : null].filter(Boolean));
    if (job.status === 'done' && job.result?.counterpart && !ws.read().list.some(w => w.id === job.result.counterpart.user.id)) { ws.addQuiet(job.result.counterpart.user, job.result.counterpart.token); redraw?.(); return; }
    if (job.status === 'running') timer = setTimeout(() => { if (root.isConnected) render(); }, 3000);
  }
  await render();
  return root;
}

// Lets a presenter act as the labelled demo counterpart (a real second workspace) and come back, without leaving the page.
function actAs(label, targetId) { const b = h('button', { class: 'btn sm', onclick: () => { ws.use(targetId); ctx.rerender(); } }, label); return b; }

// ---------------------------------------------------------------- developer
export async function developer(q) {
  const blocked = need('developer'); if (blocked) return blocked;
  const root = h('div', { class: 'stack' }); let tab = q.get('tab') || 'sites', sel = null, orderBox = h('div', null, empty('Order an audit to see it here.'));
  const tabs = [['sites', 'Sites'], ['deals', 'Matches & deals'], ['market', 'Owner listings']];
  async function draw() {
    const nav = h('div', { class: 'tabs' }, tabs.map(([k, l]) => h('button', { class: tab === k ? 'on' : '', onclick: () => { tab = k; draw(); } }, l)));
    const body = h('div'); root.replaceChildren(nav, body);
    body.append(await ({ sites, deals, market }[tab])());
  }
  async function sites() {
    const [parcels, pf, market0] = await Promise.all([api('/parcels'), api('/pool/portfolio'), api('/marketplace').catch(() => [])]);
    const leased = market0.filter(m => m.my_interest.disclosed_boundary).map(m => ({ geometry: m.my_interest.disclosed_boundary, label: m.agent_demo ? 'Leased from the Landowner agent (demo)' : 'Leased parcel' }));
    const mapCol = await parcelPicker({ saved: parcels, leased, onSaved: p => { sel = p; draw(); } });
    const type = h('select', null, ['wind', 'solar', 'hybrid'].map(x => h('option', { value: x }, x)));
    return h('div', { class: 'stack' }, await neighbourhoodCard(draw), h('div', { class: 'cols wide-r' }, h('div', { class: 'card stack' }, h('h3', null, '1 · Choose a site'), mapCol, parcelList(parcels, sel?.id, p => { sel = p; draw(); }, async p => { await guard(() => api('/parcels/' + p.id, { method: 'DELETE' })); draw(); })),
      h('div', { class: 'stack' }, h('div', { class: 'card stack' }, h('h3', null, '2 · Audit or add to the pool'),
        sel ? [h('b', null, sel.label), auditComposer(sel, { onOrder: o => orderBox.replaceChildren(orderPanel(o)) }), h('hr'),
          h('div', null, h('b', null, 'Add this site to the pool'), h('p', { class: 'small muted' }, 'The matcher audits it internally, then looks for other developers\' sites within 1.5 km and sends both sides an anonymous teaser (technology, area band, verdict band, distance band). Names, coordinates and parcel ids are never in a teaser.')),
          field('Project type', type), h('button', { class: 'btn', onclick: e => guard(async () => { const r = await api('/pool/portfolio', { method: 'POST', body: { parcel_id: sel.id, project_type: type.value } }); toast(r.status === 'registered' ? `Registered. New matches: ${r.new_matches}` : 'Not added: ' + (r.reasons || []).join('; ')); draw(); }, e.target) }, 'Add to pool (screening takes up to two minutes)')] : empty('Select a site first.')),
        h('div', { class: 'card stack' }, h('h3', null, 'Audit result'), orderBox),
        h('div', { class: 'card stack' }, h('h3', null, 'Your pool portfolio'), pf.length ? h('div', { class: 'list' }, pf.map(p => h('div', { class: 'item' }, h('div', { class: 't' }, h('b', null, p.label), h('span', { class: 'small muted' }, `${p.project_type} · ${p.audit?.verdict || ''} ${p.audit?.score ?? ''}`, p.reason ? ' · ' + p.reason : '')),
          h('div', { class: 'row' }, chip(p.status, p.status === 'registered' ? 'good' : p.status === 'rejected' ? 'bad' : ''),
            p.status === 'registered' && h('button', { class: 'btn sm', title: 'Creates a second, labelled demo workspace with a site next to this one', onclick: e => guard(async () => { const r = await api('/demo/counterpart', { method: 'POST', body: { pool_parcel_id: p.id } }); ws.addQuiet(r.user, r.token); toast('Demo counterpart created. Open "Matches & deals" to act as it.'); draw(); }, e.target) }, '+ demo counterpart'),
            p.status === 'registered' && h('button', { class: 'btn sm danger', onclick: e => guard(async () => { await api('/pool/portfolio/' + p.id, { method: 'DELETE' }); draw(); }, e.target) }, 'Withdraw'))))) : empty('Nothing in the pool yet.')))));
  }
  async function deals() {
    const [teasers, deals] = await Promise.all([api('/pool/teasers'), api('/pool/deals')]);
    const box = h('div', { class: 'stack' }); const byId = new Map(deals.map(d => [d.match_id, d]));
    const ids = [...new Set([...teasers.map(t => t.match_id), ...deals.map(d => d.match_id)])];
    for (const id of ids) box.append(dealCard(id, teasers.find(t => t.match_id === id), byId.get(id), draw));
    const list = ws.read().list, me2 = ws.current, cp = list.find(x => x.persona === 'demo-counterpart' && x.country === me2.country), back = list.find(x => x.persona !== 'demo-counterpart' && x.role === 'developer');
    const switcher = me2.persona === 'demo-counterpart' ? (back ? h('div', { class: 'callout warn row between' }, h('span', null, 'You are acting as the demo counterpart. Its consent and signature are yours to give.'), actAs('Back to ' + back.name, back.id)) : null) : (cp ? h('div', { class: 'callout row between' }, h('span', null, 'The other side of this deal is a demo workspace. Switch to it to give its consent, payment and signature.'), actAs('Act as ' + cp.name, cp.id)) : null);
    return h('div', { class: 'stack' }, switcher, h('div', { class: 'callout' }, 'Process: anonymous teaser → both consent → both payments locked → NDA signed by each party for itself → disclosure plus joint calculation. Proximity alone does not establish a continuous land block or prove a joint benefit.'),
      ids.length ? box : empty('No matches yet. Add a site to the pool; a match appears when another developer has a site within 1.5 km. To try the full flow alone, add a demo counterpart on the Sites tab.'));
  }
  async function market() {
    const items = await api('/marketplace');
    if (!items.length) return empty('No owner has published a listing for your country yet. An owner must consent, attach an audit and publish. Tip: "Build demo neighbourhood" on the Sites tab creates one.');
    return h('div', { class: 'list' }, items.map(m => {
      const msg = h('input', { placeholder: 'Message to the owner (optional)', 'aria-label': 'Message to the owner', style: 'max-width:260px' });
      const mi = m.my_interest;
      return h('div', { class: 'item' }, h('div', { class: 't' }, h('b', null, `${m.deal_type} · ${num(m.area_ha)} ha · ${m.region}`),
        h('span', { class: 'small muted' }, `Audit ${m.audit.verdict} ${m.audit.score}/100 (${m.audit.project_type}) · ${m.audit.data_complete ? 'all sources answered' : 'data incomplete'} · ${m.ownership}${m.demo ? ' · demo' : ''}${m.agent_demo ? ' · Landowner agent (demo)' : ''}`)),
        mi.status === 'none' ? h('div', { class: 'row' }, msg, h('button', { class: 'btn sm', onclick: e => guard(async () => { await api(`/marketplace/${m.id}/interest`, { method: 'POST', body: { message: msg.value || (m.agent_demo ? 'We would like to lease this parcel for our project' : '') } }); toast(m.agent_demo ? 'Leased: the demo Landowner agent accepted' : 'Request sent'); draw(); }, e.target) }, m.agent_demo ? 'Take on lease' : 'Ask for the boundary'))
          : chip(mi.status === 'accepted' && m.agent_demo ? 'leased - demo Landowner agent accepted' : mi.status, mi.status === 'accepted' ? 'good' : ''),
        mi.disclosed_boundary && h('details', null, h('summary', null, 'Boundary'), h('pre', { class: 'json' }, JSON.stringify(mi.disclosed_boundary))));
    }));
  }
  await draw(); return root;
}

const PROFILE = {
  DE: [['company_name', 'Company'], ['street', 'Street'], ['postal_code', 'Postal code (5 digits)'], ['city', 'City'], ['representative', 'Authorised representative, e.g. "Anna Müller, Geschäftsführerin"'], ['commercial_register', 'Commercial register (optional)'], ['email', 'E-mail'], ['phone', 'Phone (revealed only after signing)']],
  IN: [['company_name', 'Company'], ['address', 'Registered office'], ['state', 'State'], ['pin_code', 'PIN code (6 digits)'], ['representative', 'Authorised signatory, e.g. "Meera Shah, Director"'], ['registration_no', 'CIN / LLPIN (optional)'], ['gstin', 'GSTIN (optional)'], ['email', 'E-mail'], ['phone', 'Phone (revealed only after signing)']],
};

const HIDE = new Set(['match_id', 'teaser_id', 'your_parcel_id', 'note']);
const flat = (o, pre = '') => Object.entries(o || {}).filter(([k]) => !HIDE.has(k)).flatMap(([k, v]) => v && typeof v === 'object' ? flat(v, k.replace(/_/g, ' ') + ' ') : [`${pre}${k.replace(/_/g, ' ')}: ${v}`]);

function dealCard(id, teaser, deal, redraw) {
  const d = deal || { status: 'not_started', teaser, next: 'consent' }; const t = d.teaser || teaser || {};
  const card = h('div', { class: 'card stack' });
  const head = h('div', { class: 'row between' }, h('div', null, h('b', null, `Match ${id.slice(0, 8)}`), h('div', { class: 'small muted' }, flat(t).join(' · '))), chip(d.status.replace(/_/g, ' '), d.status === 'revealed' ? 'good' : ['declined', 'expired', 'failed'].includes(d.status) ? 'bad' : 'info'));
  card.append(head);
  const consent = dec => e => guard(async () => { await api(`/pool/deals/${id}/consent`, { method: 'POST', body: { decision: dec } }); redraw(); }, e.target);
  if (d.status === 'not_started' || d.status === 'pending_consent') {
    const mine = d.you?.consented;
    card.append(h('div', { class: 'row' }, !mine && h('button', { class: 'btn primary', onclick: async e => { const inputs = {}; const dlg = h('div', { class: 'card stack' }, h('b', null, 'Your company details (printed in the NDA; e-mail and phone are shown to the counterpart only after signing)'), ...PROFILE[country()].map(([k, l]) => field(l, inputs[k] = h('input', { value: '' }))), h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: ev => guard(async () => { await api('/pool/profile', { method: 'PUT', body: Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value])) }); await api(`/pool/deals/${id}/consent`, { method: 'POST', body: { decision: 'accept' } }); redraw(); }, ev.target) }, 'Save details and accept'), h('button', { class: 'btn', onclick: () => dlg.remove() }, 'Cancel'))); card.append(dlg); } }, 'Accept introduction'),
      mine && chip('You accepted - waiting for the other side', 'warn'), h('button', { class: 'btn danger', onclick: consent('decline') }, 'Decline')));
  } else if (d.order) {
    card.append(orderPanel(d.order));
    if (d.status === 'awaiting_signatures') card.append(signBlock(id, d, redraw));
    if (['declined', 'expired', 'failed'].includes(d.status)) card.append(h('div', { class: 'callout bad' }, 'This deal ended before disclosure. No result hash is submitted; use the protocol refund for your payment.'));
  } else if (['declined', 'expired', 'failed'].includes(d.status)) card.append(h('div', { class: 'callout bad' }, 'This deal ended before any payment.'));
  return card;
}

function signBlock(id, d, redraw) {
  if (d.you?.signed) return h('div', { class: 'callout good' }, 'You signed. Waiting for the other side. Nothing is disclosed until both sign.');
  if (!(d.own_paid && d.counterpart_paid)) return h('div', { class: 'callout warn' }, d.own_paid ? 'Your payment is locked. The NDA names both companies, so it opens when the other side has locked theirs.' : 'Lock your payment first. The NDA opens when both payments are locked.');
  const name = h('input', { placeholder: 'Your full name' }), role = h('input', { placeholder: 'Your role / title' });
  return h('div', { class: 'stack' }, h('b', null, 'Non-disclosure agreement'), h('div', { class: 'row' }, h('button', { class: 'btn', onclick: async () => download(await api(`/pool/deals/${id}/nda.pdf`, { blob: true }), 'nda.pdf') }, 'Download NDA (PDF)')),
    field('Your name', name), field('Your role', role),
    h('p', { class: 'small muted' }, 'Signing is a simple electronic acceptance of the exact PDF you downloaded (its SHA-256 is checked). It is not a qualified electronic signature. You sign only for yourself; the other side signs separately.'),
    h('button', { class: 'btn primary', onclick: e => guard(async () => {
      const pdf = await api(`/pool/deals/${id}/nda.pdf`, { blob: true }); const buf = await pdf.arrayBuffer(); const sha = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buf))].map(b => b.toString(16).padStart(2, '0')).join('');
      await api(`/pool/deals/${id}/sign`, { method: 'POST', body: { signer_name: name.value, signer_role: role.value, document_sha256: sha, accept: true } }); toast('Signed'); redraw(); }, e.target) }, 'I accept this NDA for my company'));
}

// ---------------------------------------------------------------- orders
export async function orders(q, params) {
  const blocked = need(); if (blocked) return blocked;
  if (params[0]) { const o = await api('/orders/' + params[0]); return h('div', { class: 'stack' }, h('a', { href: '#/orders' }, '← All orders'), h('div', { class: 'card' }, orderPanel(o))); }
  const list = await api('/orders');
  return list.length ? h('div', { class: 'card' }, h('table', { class: 't' }, h('thead', null, h('tr', null, ['Service', 'Subject', 'Price', 'State', 'Created', ''].map(x => h('th', null, x)))),
    h('tbody', null, list.map(o => h('tr', null, h('td', null, o.title), h('td', null, o.subject), h('td', null, o.price.display), h('td', null, stateChip(o)), h('td', null, fmtTime(o.created_at)), h('td', null, h('a', { href: '#/orders/' + o.id }, 'Open'))))))) : empty('No orders yet.');
}

export async function map(q = new URLSearchParams()) {
  const blocked = need(); if (blocked) return blocked;
  const w = ws.current, el = h('div', { class: 'map tall' }), out = h('div', { class: 'card' }, 'Click a parcel.');
  const m = await parcelMap(el, { country: w.country, saved: await api('/parcels'), onSelect: p => out.replaceChildren(h('b', null, p.label), h('div', { class: 'small muted' }, `${num(p.area_ha)} ha · ${p.source}`), h('div', { class: 'row', style: 'margin-top:.6rem' }, h('button', { class: 'btn primary sm', onclick: e => guard(async () => { await api('/parcels', { method: 'POST', body: { source: p.source, ref: p.ref } }); toast('Saved to your parcels - open your workflow to audit it'); }, e.target) }, 'Save to my parcels')))});
  if (q.get('find') && !m.find(q.get('find'))) toast('No parcel matches "' + q.get('find') + '" in the loaded map', true);
  return h('div', { class: 'stack' }, el, m.info, out);
}
