// The order panel: price before payment, the four separate payment facts, the timeline, and the result renderers.
// The same panel serves all three services; it reloads from the server by order id, so a refresh never loses state.
import { showDevNotices, api, h, chip, fmtTime, fmtMs, num, money, toast, guard, download, copy, hash, kv, spinner, empty } from './core.js';
import { cropSection } from './crop.js';

const ACTIVE = ['quoted', 'awaiting_payment', 'paid', 'waiting', 'running', 'delivered'];
const STATE_TEXT = { quoted: 'Ready to pay', awaiting_payment: 'Waiting for funds to be locked', paid: 'Paid - starting', waiting: 'Paid - waiting for the other side', running: 'Working', delivered: 'Report ready', failed: 'Not delivered', expired: 'Payment window expired' };
const STATE_KIND = { delivered: 'good', failed: 'bad', expired: 'bad', waiting: 'warn' };

export function stateChip(o) { return chip(STATE_TEXT[o.state] || o.state, STATE_KIND[o.state] || 'info'); }

function facts(o) {
  const p = o.payment;
  if (p.mode === 'demo-seed') return h('div', { class: 'callout' }, h('b', null, 'Demo seed. '), 'This audit belongs to the platform-provided Landowner agent. No payment and no Cardano transaction: it only exists so the neighbourhood demo has a parcel to lease.');
  if (p.mode !== 'masumi' && !showDevNotices) return null;
  if (p.mode !== 'masumi') return h('div', { class: 'callout bad' }, h('b', null, 'UNPAID DEV MODE. '), 'No payment and no Cardano transaction exist for this order. This mode is for developers only.');
  const step = (title, done, text, tx) => h('div', { class: 'step ' + (done ? 'done' : (o.state === 'failed' ? 'bad' : 'wait')) }, h('b', null, (done ? '✓ ' : '') + title), text, tx && h('div', { class: 'hash' }, 'tx ' + tx));
  return h('div', { class: 'stepper', 'aria-label': 'Payment facts' },
    step('Funds locked', p.funds_locked, p.funds_locked ? 'Confirmed on-chain' : 'Not yet', p.funds_locked_tx),
    step('Report ready', p.report_ready, p.report_ready ? 'Stored and hashed' : 'Not yet'),
    step('Result hash on-chain', p.result_hash_confirmed, p.result_hash_confirmed ? 'Confirmed' : 'Not yet', p.result_hash_tx),
    step('Seller paid out', p.seller_paid_out, p.seller_paid_out ? 'Settled' : 'After the dispute window', p.settlement_tx));
}

function payBlock(o, refresh) {
  const price = h('b', null, o.price.display);
  if (o.state === 'quoted') {
    return h('div', { class: 'callout' }, h('div', { class: 'row between' },
      h('div', null, 'Price: ', price, h('div', { class: 'small muted' }, o.payment.mode === 'masumi'
        ? 'Funds are locked in a Masumi smart contract on Cardano preprod (test funds). They are released to the agent only after the result hash is confirmed and the dispute window has passed.'
        : (showDevNotices ? 'Dev mode: nothing is charged.' : ''))),
      h('button', { class: 'btn primary', onclick: e => guard(async () => { await api(`/orders/${o.id}/pay`, { method: 'POST' }); refresh(); }, e.target) }, o.payment.mode === 'masumi' ? 'Create payment request' : (showDevNotices ? 'Start (unpaid dev)' : 'Start'))));
  }
  if (o.state === 'awaiting_payment') {
    return h('div', { class: 'callout warn' }, h('b', null, 'Waiting for ', o.price.display, ' to be locked'),
      h('p', { class: 'small' }, 'Lock the funds from a Masumi/Sokosumi wallet using this payment identifier before ', fmtMs(o.payment.pay_by), '. Nothing runs until the lock is confirmed on-chain. Reloading this page does not create a second request.'),
      h('div', { class: 'row' }, hash(o.payment.blockchain_identifier), h('button', { class: 'btn sm', onclick: () => copy(o.payment.blockchain_identifier) }, 'Copy')),
      o.payment.buyer_can_pay_with_demo_wallet && h('p', null, h('button', { class: 'btn primary', onclick: e => guard(async () => { await api(`/orders/${o.id}/pay-demo-wallet`, { method: 'POST' }); toast('Purchase submitted. Waiting for confirmation.'); refresh(); }, e.target) }, 'Pay with the demo test wallet'),
        h('span', { class: 'small muted' }, ' real preprod transaction, funded by the operator')));
  }
  if (o.state === 'waiting') return h('div', { class: 'callout warn' }, 'Your payment is locked. Waiting for: ', h('b', null, o.payment.waiting_for || 'the other side'), '. Nothing is delivered until then.');
  if (o.state === 'failed') return h('div', { class: 'callout bad' }, h('b', null, 'Not delivered. '), o.error || 'The service could not produce a result.', h('p', { class: 'small' }, 'No result hash was submitted, so the funds stay refundable through the Masumi protocol. This is different from a negative report, which is a completed service.'));
  if (o.state === 'expired') return h('div', { class: 'callout bad' }, 'The payment window passed without locked funds. Nothing was charged. Create a new order to try again.');
  if (['paid', 'running'].includes(o.state)) return h('div', { class: 'callout' }, spinner(STATE_TEXT[o.state] + '… this can take up to two minutes for live data sources.'));
  return null;
}

export function orderPanel(initial, { onChange } = {}) {
  const root = h('div', { class: 'stack' });
  let order = initial, timer = null;
  async function load() {
    try { order = await api(`/orders/${order.id}`); } catch (e) { if (e.status === 404) { root.replaceChildren(empty('Order not found in this workspace.')); return; } }
    render(); onChange?.(order);
    clearTimeout(timer);
    if (root.isConnected && ['awaiting_payment', 'paid', 'waiting', 'running'].includes(order.state) || (order.payment.mode === 'masumi' && order.state === 'delivered' && !order.payment.seller_paid_out && root.isConnected)) timer = setTimeout(load, 3500);
  }
  function render() {
    const o = order;
    const children = [h('div', { class: 'row between' }, h('div', null, h('b', null, o.title), ' ', h('span', { class: 'muted' }, '· ' + o.subject), h('div', { class: 'small muted' }, `${o.country} · ${fmtTime(o.created_at)} · order ${o.id.slice(0, 8)}`)), stateChip(o)),
      facts(o), payBlock(o, load)];
    if (o.state === 'delivered') children.push(h('div', { id: 'result-slot' }, spinner('Loading result…')));
    const tech = () => h('details', null, h('summary', null, 'Technical details and timeline'), kv([['Order id', hash(o.id)], ['Input hash', hash(o.input_hash)], ['Result hash', o.result_hash ? hash(o.result_hash) : '-'], ['Channel', o.channel], ['Price (base units)', o.price.amount + ' ' + o.price.symbol + ' units'],
      ['Payment state', o.payment.on_chain_state || o.payment.stage || '-']]),
      h('div', { class: 'stack', style: 'margin-top:.6rem' }, (o.events || []).map(e => h('div', { class: 'bubble' }, h('time', null, fmtTime(e.at)), e.event.replace(/_/g, ' '), e.data && Object.keys(e.data).length ? ' - ' + Object.entries(e.data).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', ') : ''))));
    if (o.state !== 'delivered') children.push(tech());
    root._tech = tech;
    root.replaceChildren(...children.filter(Boolean));
    if (o.state === 'delivered') loadResult();
  }
  async function loadResult() {
    const slot = root.querySelector('#result-slot'); if (!slot) return;
    try {
      const r = await api(`/orders/${order.id}/result`);
      slot.replaceChildren(renderResult(order, r), root._tech(), resultActions(order, r));
    } catch (e) { slot.replaceChildren(empty(e.message)); }
  }
  load();
  return root;
}

function resultActions(o, r) {
  const out = h('div', { class: 'stack' });
  out.append(h('div', { class: 'row actions' },
    h('button', { class: 'btn primary', onclick: async e => guard(async () => {
      const v = await api(`/orders/${o.id}/verify`);
      box.replaceChildren(h('div', { class: v.report_hash_matches && (!v.recomputation || v.recomputation.status === 'pass') ? 'callout good' : 'callout bad' },
        h('b', null, v.report_hash_matches ? '✓ Stored report matches its hash' : '✗ Hash mismatch'), v.recomputation && h('div', null, `Recomputation of ${v.recomputation.checked_findings} findings: `, h('b', null, v.recomputation.status)),
        v.crop_recomputation && h('div', null, `Recomputation of the crop section (${v.crop_recomputation.checked_parcels} fields, from the stored satellite observations): `, h('b', null, v.crop_recomputation.status)),
        h('p', { class: 'small' }, v.what_a_hash_proves), h('pre', { class: 'json' }, JSON.stringify(v.chain, null, 1))));
    }, e.target) }, 'Verify result'),
    h('button', { class: 'btn', onclick: () => download(new Blob([JSON.stringify(r.report, null, 2)], { type: 'application/json' }), `agroland-${o.service}-${o.id.slice(0, 8)}.json`) }, 'Download JSON'),
    h('button', { class: 'btn', onclick: () => download(new Blob([r.markdown], { type: 'text/markdown' }), `agroland-${o.service}-${o.id.slice(0, 8)}.md`) }, 'Download Markdown'),
    o.service === 'lease_check' && h('button', { class: 'btn', onclick: async () => download(await api(`/orders/${o.id}/reminders.ics`, { blob: true }), 'lease-reminders.ics') }, 'Calendar reminders (.ics)')));
  const box = h('div'); out.append(box, h('div', { class: 'small muted' }, 'Report SHA-256 ', hash(r.report_sha256), ' - proves the stored report is unchanged, not that its data is true.'));
  return out;
}

// ---------------------------------------------------------------- result renderers
export function renderResult(o, r) {
  return { land_audit: auditResult, lease_check: leaseResult, pool_access: poolResult }[o.service](o, r.report);
}

const limits = list => h('details', null, h('summary', null, 'Limits of this report'), h('ul', null, (list || []).map(x => h('li', null, x))));

function auditResult(o, rep) {
  const a = rep.audit_conclusion, q = rep.data_quality, g = rep.geometric_signal;
  return h('div', { class: 'stack' },
    h('div', { class: 'three' },
      h('div', null, h('h4', null, 'Audit conclusion'), h('div', { class: 'verdict ' + a.verdict }, a.verdict.replace('_', ' ')), h('div', null, `Score ${a.score}/100`), h('div', { class: 'small muted' }, a.meaning + '. A good verdict is only as complete as the data-quality column.')),
      h('div', null, h('h4', null, 'Preliminary geometric signal'), g ? h('div', null, h('span', { class: 'sig ' + g.geometry_signal }), h('b', null, g.geometry_signal), h('div', { class: 'small' }, `${g.distance_to_axis_m} m to the motorway axis; 500 m corridor: ${g.corridors['500'].coverage}; 200 m: ${g.corridors['200'].coverage}`), h('div', { class: 'small muted' }, 'Geometry only. Legal status: ' + g.legal_status + '.')) : h('div', { class: 'small muted' }, 'No geometric corridor signal for this site (available for the Magdeburg ALKIS fragment).')),
      h('div', null, h('h4', null, 'Data quality'), q.complete ? chip('all sources answered', 'good') : chip('incomplete', 'warn'), h('div', { class: 'small' }, q.note), q.unavailable_checks.length ? h('div', { class: 'small' }, 'Unavailable: ' + q.unavailable_checks.join(', ')) : null)),
    h('div', null, h('h4', null, 'By technology'), kv(Object.entries(a.technology_assessment).map(([t, v]) => [t, h('span', null, `${v.verdict.replace('_', ' ')} (${v.score}/100)`, v.blockers?.length ? h('div', { class: 'small', style: 'color:var(--bad)' }, 'Blockers: ' + v.blockers.join('; ')) : null, v.conditions?.length ? h('div', { class: 'small', style: 'color:var(--warn)' }, 'Conditions: ' + v.conditions.join('; ')) : null)]))),
    a.warnings.length ? h('div', { class: 'callout warn' }, h('b', null, 'Warnings'), h('ul', null, a.warnings.map(w => h('li', null, w)))) : null,
    h('details', null, h('summary', null, 'Per-source data quality'), kv(Object.entries(q.per_check))),
    h('details', null, h('summary', null, 'Site facts'), h('pre', { class: 'json' }, JSON.stringify(rep.site_facts, null, 1))),
    limits(rep.limitations));
}

function leaseResult(o, rep) {
  const s = rep.summary, m = rep.meta, cur = m.currency;
  const fm = n => money(n, cur);
  return h('div', { class: 'stack' },
    h('div', { class: 'tiles stats' },
      h('div', { class: 'tile warn' }, h('div', { class: 'n' }, fm(s.identified_per_year)), h('div', { class: 'l' }, 'Identified from your documents / year')),
      h('div', { class: 'tile info' }, h('div', { class: 'n' }, fm(s.negotiable_per_year)), h('div', { class: 'l' }, 'Negotiation opportunity / year (not a loss)')),
      h('div', { class: 'tile good', id: 'achieved' }, h('div', { class: 'n' }, fm(s.achieved_per_year)), h('div', { class: 'l' }, 'Savings achieved (you record these)')),
      h('div', { class: 'tile' }, h('div', { class: 'n' }, s.expiring_contracts.length), h('div', { class: 'l' }, 'Leases expiring soon'))),
    h('p', { class: 'small muted' }, `${m.farm_name} · ${s.contracts_count} leases · ${num(s.total_area_contract)} ${m.area_unit} · rent ${fm(s.total_rent_per_year)}/year · verification: `, chip(rep.verification.status, rep.verification.status === 'pass' ? 'good' : 'bad')),
    h('h4', { class: 'sec' }, 'Findings'),
    h('table', { class: 't findings' }, h('thead', null, h('tr', null, ['Type', 'Lease', 'Finding', `${cur}/year`, ''].map(x => h('th', null, x)))),
      h('tbody', null, rep.findings.map(f => h('tr', null,
        h('td', null, chip(f.category, f.category === 'identified' ? 'warn' : f.category === 'negotiable' ? 'info' : '')), h('td', null, f.contract_id), h('td', null, f.explanation), h('td', null, f.amount_per_year ? fm(f.amount_per_year) : '-'),
        h('td', null, f.category !== 'expiring' && h('button', { class: 'btn sm', onclick: e => recordOutcome(o, f, e.target) }, 'Record saving')))))),
    s.expiring_contracts.length ? h('div', { class: 'callout warn' }, h('b', null, 'Deadlines'), h('ul', null, s.expiring_contracts.map(e => h('li', null, `${e.contract_id} (${e.owner}) ends ${e.end_date} - ${e.days_left} days`)))) : null,
    rep.warnings.length ? h('div', { class: 'callout warn' }, rep.warnings.map(w => h('div', null, w))) : null,
    h('p', { class: 'small muted' }, m.benchmark_note), cropSection(rep), limits(rep.limitations));
}

async function recordOutcome(o, f, btn) {
  const raw = prompt(`How much per year did you actually save on ${f.contract_id}? (0 = nothing yet)`, '0'); if (raw == null) return;
  const note = prompt('Short note (optional): e.g. "owner agreed to a new rent from January"', '') || '';
  await guard(async () => { const r = await api('/farm/outcomes', { method: 'POST', body: { order_id: o.id, finding_key: `${f.type}:${f.contract_id}`, amount_per_year: Number(raw), note } }); toast('Recorded. Achieved so far: ' + r.achieved_per_year); const t = document.querySelector('#achieved .n'); if (t) t.textContent = r.achieved_per_year; }, btn);
}

function poolResult(o, rep) {
  const cp = rep.disclosure.counterpart || {}, co = cp.company || {}, par = cp.parcel || {}, jp = rep.joint_plan || {}, plan = jp.plan || {};
  const shares = plan.shares_bp || {}, jproj = plan.joint_project || {}, syn = plan.synergy || {}, parties = plan.parties || [];
  const eur = n => n == null ? '-' : (o.country === 'IN' ? '₹' : '€') + Number(n).toLocaleString(o.country === 'IN' ? 'en-IN' : 'en-GB', { maximumFractionDigits: 0 });
  return h('div', { class: 'stack' },
    h('div', { class: 'callout good' }, h('b', null, 'Disclosed after both NDAs were signed')),
    kv([['Counterpart', co.company_name], ['Representative', co.representative], ['E-mail', co.email], ['Phone', co.phone], ['Their parcel', par.label || par.municipality || par.alkis_parcel_id], ['Technology', par.assessed_technology], ['Area (ha)', par.area_ha]]),
    h('h4', null, 'Preliminary joint calculation'),
    plan.viable === false || plan.pooling_beneficial === false
      ? h('div', { class: 'callout warn' }, h('b', null, plan.viable === false ? 'On these assumptions the joint project is not viable. ' : 'Pooling does not create value on these assumptions. '), 'Being close is not enough: the model compares the joint project with each site alone. The split below is the fall-back key (', plan.method_applied || 'area', '), not a recommendation to proceed.')
      : h('div', { class: 'callout good' }, 'Pooling creates value on these assumptions (screening level).'),
    h('div', { class: 'tiles' },
      h('div', { class: 'tile' }, h('div', { class: 'n' }, num(jproj.capacity_mw) + ' MW'), h('div', { class: 'l' }, 'Joint capacity')),
      h('div', { class: 'tile ' + ((jproj.npv_eur ?? jproj.npv_inr) >= 0 ? 'good' : 'warn') }, h('div', { class: 'n' }, eur(jproj.npv_eur ?? jproj.npv_inr)), h('div', { class: 'l' }, 'Joint NPV (25 years)')),
      h('div', { class: 'tile' }, h('div', { class: 'n' }, eur(syn.total_eur ?? syn.total_inr)), h('div', { class: 'l' }, 'Value of pooling vs. each site alone'))),
    Object.keys(shares).length ? kv(parties.length ? parties.map((x, i) => [x.company_name || x.label || Object.keys(shares)[i], `${((shares[x.label] ?? Object.values(shares)[i]) / 100).toFixed(2)} % (${shares[x.label] ?? Object.values(shares)[i]} basis points)`]) : Object.entries(shares).map(([k, v]) => [k, `${(v / 100).toFixed(2)} % (${v} basis points)`])) : null,
    plan.warnings?.length ? h('div', { class: 'callout warn' }, h('b', null, 'Model warnings'), plan.warnings.map(w => h('div', null, w))) : null,
    h('details', null, h('summary', null, 'Full plan (JSON)'), h('pre', { class: 'json' }, JSON.stringify(jp, null, 1))),
    h('div', { class: 'row' }, rep.documents.map(d => h('button', { class: 'btn', onclick: async () => download(await api(`/pool/deals/${rep.match_id}/documents/${d.kind}.pdf`, { blob: true }), `${d.kind}.pdf`) }, `Download ${d.kind.replace('_', ' ')} (PDF)`))),
    h('div', { class: 'small muted' }, rep.documents.map(d => h('div', null, `${d.kind}.pdf sha256 `, hash(d.sha256)))), limits(rep.limitations));
}
