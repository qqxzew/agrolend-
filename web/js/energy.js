import { api, ws, h, chip, field, num, money, guard, toast, empty, fmtTime, parcelLabel } from './core.js';

const TECH = { solar: 'Solar', wind: 'Wind', hybrid: 'Solar & wind' };
const title = (eyebrow, heading, text) => h('div', { class: 'section-heading' }, eyebrow && h('span', { class: 'eyebrow' }, eyebrow), h('h3', null, heading), text && h('p', null, text));

export async function landSearch({ onSelect } = {}) {
  const root = h('div', { class: 'card stack' }), results = h('div', { class: 'stack' });
  const tech = h('select', null, h('option', { value: '' }, 'Any technology'), ...Object.entries(TECH).map(([k, text]) => h('option', { value: k }, text)));
  const region = h('input', { type: 'search', placeholder: 'City, district or state', 'aria-label': 'Filter land by region' });
  const area = h('input', { type: 'number', min: 0, max: 1000000, step: .5, placeholder: 'Any area' });
  async function search() {
    const query = new URLSearchParams({ region: region.value.trim(), min_area_ha: String(Number(area.value) || 0) });
    if (tech.value) query.set('project_type', tech.value);
    const [network, listings] = await Promise.all([api('/land/sites?' + query), api('/marketplace')]);
    const offers = listings.filter(m => (!tech.value || [tech.value, 'hybrid'].includes(m.audit.project_type)) && m.area_ha >= (Number(area.value) || 0) && m.region.toLowerCase().includes(region.value.trim().toLowerCase()));
    results.replaceChildren(
      h('div', { class: 'row between' }, h('h4', { class: 'sec' }, 'Owner offers'), chip(offers.length + ' results')),
      offers.length ? h('div', { class: 'land-results' }, offers.map(m => {
        const interest = m.my_interest, message = h('input', { placeholder: 'Tell the owner about your project', 'aria-label': 'Message to the owner' });
        return h('article', { class: 'land-result' }, h('div', { class: 'row between' }, chip(TECH[m.audit.project_type] || 'Energy site', 'info'), chip(m.deal_type === 'lease' ? 'For lease' : 'For sale')),
          h('h4', null, `${num(m.area_ha)} ha · ${m.region}`), h('p', { class: 'small muted' }, money(m.price, ws.current.country === 'DE' ? 'EUR' : 'INR') + (m.deal_type === 'lease' ? (ws.current.country === 'DE' ? ' / ha / year' : ' / acre / year') : ' total')),
          h('div', { class: 'small muted' }, `${m.audit.verdict.replaceAll('_', ' ')} · ${m.audit.score}/100 · ${m.audit.data_complete ? 'sources complete' : 'some sources unavailable'}`),
          interest.status === 'none' ? h('details', { class: 'request-boundary' }, h('summary', null, 'Request the boundary'), h('div', { class: 'stack tight' }, message,
            h('button', { class: 'btn primary sm', onclick: e => guard(async () => { await api(`/marketplace/${m.id}/interest`, { method: 'POST', body: { message: message.value } }); toast('Request sent'); await search(); }, e.target) }, 'Send request')))
            : chip(interest.status === 'accepted' ? 'Boundary access granted' : 'Request ' + interest.status, interest.status === 'accepted' ? 'good' : 'info'),
          interest.disclosed_boundary && h('button', { class: 'btn sm', onclick: e => guard(async () => {
            const p = await api('/parcels', { method: 'POST', body: { source: 'drawn', ref: 'listing-' + m.id, geometry: interest.disclosed_boundary, label: 'Owner-shared site · ' + m.region } });
            await onSelect?.(p);
          }, e.target) }, 'Open this site →'),
          m.agent_demo && chip('Demonstration owner', 'info'));
      })) : h('div', { class: 'empty compact' }, 'No published offers match these filters. Explore the map or try another region.'),
      h('div', { class: 'row between' }, h('h4', { class: 'sec' }, 'Sites in the land database'), chip(network.length + ' sites')),
      network.length ? h('div', { class: 'land-results' }, network.map(s => h('article', { class: 'land-result' }, h('div', { class: 'row between' }, chip(TECH[s.project_type], 'good'), s.own && chip('Your site')), h('h4', null, parcelLabel(s.label)),
        h('p', { class: 'small muted' }, `${num(s.area_ha)} ha · ${s.region}`), h('p', { class: 'small muted' }, s.own ? 'Included with your consent. Cluster proposals appear under Clusters.' : 'Open to nearby cluster proposals. Exact boundaries and contact details stay private.'))))
        : h('div', { class: 'empty compact' }, 'No registered sites match yet. Register a site you control to start finding a cluster.'));
  }
  root.append(title('LAND DISCOVERY', 'Find land and nearby projects', 'Owner offers are published with consent. The land database contains sites whose participants have agreed to cluster matching.'),
    h('form', { class: 'land-filters', onsubmit: e => { e.preventDefault(); guard(search, submit); } }, field('Technology', tech), field('Region', region), field('Minimum area · ha', area),
      h('button', { class: 'btn primary', type: 'submit' }, 'Find land')), results);
  const submit = root.querySelector('button[type=submit]');
  await search(); return root;
}

export async function enrollSite(parcel, { onSaved, onClusters }) {
  const own = await api('/land/sites?mine=true'), existing = own.find(s => s.parcel_id === parcel.id && s.status === 'listed');
  if (existing) return h('div', { class: 'card stack enrollment-card' }, title('LAND DATABASE', 'Your site is ready for matching', 'It is included with your consent. Joining a specific cluster always needs another decision.'),
    h('div', { class: 'row' }, chip('Registered', 'good'), chip(TECH[existing.project_type]), h('span', { class: 'small muted' }, 'Consent recorded ' + fmtTime(existing.consent_at))),
    h('button', { class: 'btn primary', onclick: onClusters }, 'View cluster proposals →'));
  const consent = h('input', { type: 'checkbox', onchange: () => { submit.disabled = !consent.checked; } });
  const tech = h('select', null, ...Object.entries(TECH).map(([value, label]) => h('option', { value }, label)));
  const region = h('input', { placeholder: 'Use the map region', maxlength: 100 });
  const submit = h('button', { class: 'btn primary', disabled: true, onclick: e => guard(async () => {
    await api('/land/sites', { method: 'POST', body: { parcel_id: parcel.id, project_type: tech.value, region: region.value, consent: consent.checked } });
    toast('Site added. Review cluster proposals when a neighbour joins.'); await onSaved();
  }, e.target) }, 'Add to land database');
  return h('div', { class: 'card stack enrollment-card' }, title('NEXT STEP', 'Find a cluster for this site', 'Add a site you control to the database. Nearby solar or wind projects can then form a proposal, with a separate decision from every participant.'),
    h('div', { class: 'listing-fields' }, field('Project technology', tech), field('Region (optional)', region)),
    h('label', { class: 'check consent-box' }, consent, h('span', null, 'I have permission to register this site and agree to matching it with nearby projects. Joining a cluster needs my separate approval.')),
    h('div', { class: 'form-footer' }, h('p', { class: 'small muted' }, 'Free registration · no payment or transfer of land rights.'), submit));
}

export async function registeredSites({ onFind, onClusters }) {
  const root = h('div', { class: 'stack' });
  async function render() {
    const current = await api('/land/sites?mine=true');
    root.replaceChildren(title('YOUR LAND DATABASE', 'Registered sites', 'Keep track of the land you have included in cluster matching. Withdrawal cancels affected cluster proposals and agreements.'),
      current.length ? h('div', { class: 'land-results' }, current.map(s => h('article', { class: 'land-result stack tight' }, h('div', { class: 'row between' }, chip(TECH[s.project_type], 'info'), chip(s.status === 'listed' ? 'In the database' : 'Withdrawn', s.status === 'listed' ? 'good' : '')),
        h('h3', null, parcelLabel(s.label)), h('p', { class: 'small muted' }, `${num(s.area_ha)} ha · ${s.region}`), h('p', { class: 'small muted' }, 'Consent recorded ' + fmtTime(s.consent_at)),
        s.status === 'listed' && h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: onClusters }, 'View clusters'), h('button', { class: 'btn sm danger', onclick: e => guard(async () => { await api('/land/sites/' + s.id, { method: 'DELETE' }); toast('Site withdrawn from matching'); await render(); }, e.target) }, 'Withdraw site')))))
        : h('div', { class: 'card empty' }, 'Your registered sites will appear here.', h('div', { class: 'row center' }, h('button', { class: 'btn primary', onclick: onFind }, 'Find a site'))));
  }
  await render(); return root;
}

const STATUS = { proposed: ['Waiting for consent', 'info'], agreed: ['Everyone agreed', 'good'], declined: ['Declined', ''], cancelled: ['Site withdrawn or changed', ''], superseded: ['New proposal available', ''] };
export async function clusterBoard({ onFind, onSites }) {
  const root = h('div', { class: 'stack' });
  let stamp = '';
  async function render() {
    const [clusters, own] = await Promise.all([api('/land/clusters'), api('/land/sites?mine=true')]);
    stamp = JSON.stringify(clusters);
    const active = clusters.filter(c => ['proposed', 'agreed'].includes(c.status)), ended = clusters.filter(c => !active.includes(c));
    root.replaceChildren(...[title('SOLAR & WIND CLUSTERS', 'Build a project together', 'Neighbouring sites within 1.5 km form a proposal. Every participant reviews the same membership and decides for themselves.'),
      h('div', { class: 'network-stats' }, [[own.filter(s => s.status === 'listed').length, 'Your registered sites'], [active.filter(c => c.status === 'proposed').length, 'Proposals to review'], [active.filter(c => c.status === 'agreed').length, 'Agreed clusters']].map(([value, label]) => h('div', null, h('b', null, value), h('span', null, label)))),
      active.length ? active.map(card) : h('div', { class: 'card cluster-empty' }, h('span', { class: 'cluster-symbol', 'aria-hidden': 'true' }, '◇'), h('h3', null, 'Your next neighbour could be the start'),
        h('p', { class: 'muted' }, own.some(s => s.status === 'listed') ? 'Your sites are in the database. A proposal appears when another participant registers a compatible nearby site.' : 'Register a site you control. A nearby solar or wind project can then become a cluster proposal.'),
        h('div', { class: 'row center' }, h('button', { class: 'btn primary', onclick: onFind }, 'Find and register a site'), h('button', { class: 'btn', onclick: onSites }, 'My sites'))),
      ended.length && h('details', null, h('summary', null, 'Previous proposals · ' + ended.length), h('div', { class: 'stack' }, ended.map(card))),
      h('p', { class: 'small muted' }, 'Agreement records mutual interest in this exact group. New members need fresh approval. Land rights, private introductions and project agreements remain separate; proximity does not prove a continuous site or an economic benefit.')].flat().filter(Boolean));
  }
  function card(cluster) {
    const [status, kind] = STATUS[cluster.status] || STATUS.proposed, open = ['proposed', 'agreed'].includes(cluster.status);
    const decide = decision => e => guard(async () => { await api(`/land/clusters/${cluster.id}/decision`, { method: 'POST', body: { decision } }); toast(decision === 'accept' ? 'Your agreement was recorded' : 'You declined this cluster'); await render(); }, e.target);
    return h('article', { class: 'card stack cluster-card' }, h('div', { class: 'row between' }, h('div', null, h('span', { class: 'eyebrow' }, TECH[cluster.project_type] + ' CLUSTER'), h('h3', null, `${cluster.site_count} sites · ${cluster.participant_count} participants`)), chip(status, kind)),
      h('div', { class: 'cluster-metrics' }, h('span', null, h('b', null, num(cluster.area_ha) + ' ha'), ' registered area'), h('span', null, 'Neighbouring boundaries · up to 1.5 km between connected sites')),
      h('div', { class: 'consent-progress', role: 'progressbar', 'aria-label': 'Participants who agreed', 'aria-valuenow': cluster.accepted_count, 'aria-valuemin': 0, 'aria-valuemax': cluster.participant_count }, h('span', { style: `width:${100 * cluster.accepted_count / cluster.participant_count}%` })),
      h('div', { class: 'row between small' }, h('b', null, `${cluster.accepted_count} of ${cluster.participant_count} participants agreed`), h('span', { class: 'muted' }, 'Every participant decides separately')),
      h('div', { class: 'cluster-members' }, cluster.members.map(m => h('div', { class: 'cluster-member' }, h('span', { class: 'cluster-member-mark' }, m.own ? '↗' : '◇'), h('div', { class: 'grow' }, h('b', null, parcelLabel(m.label)), h('span', { class: 'small muted' }, `${num(m.area_ha)} ha · ${m.region}${m.own ? ' · your site' : ''}`)), chip(m.decision === 'accept' ? 'Agreed' : m.decision === 'decline' ? 'Declined' : 'Pending', m.decision === 'accept' ? 'good' : '')))),
      cluster.status === 'agreed' && h('div', { class: 'privacy-note success' }, 'All participants agreed to explore this cluster. Exact boundaries and contacts remain private.'),
      open && h('div', { class: 'cluster-actions' }, cluster.own_decision === 'pending' ? h('button', { class: 'btn primary', onclick: decide('accept') }, 'Agree to this cluster') : chip('Your agreement is recorded', 'good'),
        h('button', { class: 'btn ghost', onclick: decide('decline') }, cluster.own_decision === 'accept' ? 'Withdraw my agreement' : 'Decline')));
  }
  async function follow() {
    if (!root.isConnected) return;
    const next = await api('/land/clusters').catch(() => null);
    if (!root.isConnected) return;
    if (next && JSON.stringify(next) !== stamp) await render();
    if (root.isConnected) setTimeout(follow, 5000);
  }
  await render(); setTimeout(follow, 5000); return root;
}
