import { api, ws, h, chip, toast, ApiError, showDevNotices } from './core.js';
import * as V from './views.js';

const ICON = {
  chat: 'M4 5h16v11H9l-5 4z', pin: 'M12 21s-6-5.6-6-10.5a6 6 0 0 1 12 0C18 15.4 12 21 12 21zM12 10.5m-2 0a2 2 0 1 0 4 0 2 2 0 1 0-4 0', map: 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14',
  up: 'M12 16V5m0 0-4 4m4-4 4 4M5 20h14', list: 'M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01', shield: 'M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6zM9 12l2 2 4-4',
  poly: 'M5 6l8-3 6 6-3 9-9-2z', lock: 'M5 11h14v9H5zM8 11V8a4 4 0 0 1 8 0v3', pie: 'M12 3a9 9 0 1 0 9 9h-9zM15 3.5A9 9 0 0 1 20.5 9H15z', euro: 'M18 6.5A7 7 0 0 0 7 12a7 7 0 0 0 11 5.5M4 10.5h10M4 13.5h9',
  cal: 'M4 5.5h16V20H4zM4 10h16M8.5 3.5v4M15.5 3.5v4', orders: 'M5 4h14v16H5zM9 9h6M9 13h6M9 17h3', layers: 'M12 3L3 8l9 5 9-5-9-5zM3 13l9 5 9-5', data: 'M7 4v14m0 0-3-3m3 3 3-3M17 20V6m0 0-3 3m3-3 3 3', user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0', menu: 'M4 7h16M4 12h16M4 17h16', search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4.5-4.5', plus: 'M12 5v14M5 12h14',
};
const ic = k => h('span', { class: 'ico', html: `<svg viewBox="0 0 24 24"><path d="${ICON[k]}"/></svg>` });
// Every destination of the previous navigation is still here; items are grouped like the original LandCheck prototype.
// Each item is tagged with the role that uses it (null = common). The sidebar shows only common items plus those of the current workspace's role.
// Items are tagged with the role that uses them (null = common). Each workflow page holds its own tabs (parcel map, listings, deals), so no duplicate entries.
const NAV = [
  ['What do you want to do?', [['chat', 'Ask the agent', 'Pick the right workflow', '#/', null], ['pin', 'Check a parcel', 'Map, audit, listings', '#/owner', 'owner'], ['euro', 'Audit my leases', 'Reports and rent reminders', '#/farm', 'farm'],
    ['shield', 'Audit a site', 'Map, pool, deals, owner listings', '#/developer', 'developer']]],
  ['Reference', [['orders', 'Orders', 'History, payment, results', '#/orders', 'any'], ['data', 'Data and sources', 'Where the numbers come from', '#/#coverage', null], ['user', 'Workspaces', 'Switch or create', '#/start', null]]],
];
const ROUTES = {
  '': { title: 'Chat', fn: V.home, nav: 'home' }, start: { title: 'Workspaces', fn: V.start, nav: 'home' }, owner: { title: 'Landowner', fn: V.owner, nav: 'owner' },
  farm: { title: 'Tenant farm', fn: V.farm, nav: 'farm' }, developer: { title: 'Energy developer', fn: V.developer, nav: 'developer' },
  map: { title: 'Map', fn: V.map, nav: 'map' }, orders: { title: 'Orders', fn: V.orders, nav: 'orders' },
};

function parse() {
  const [path, qs] = location.hash.replace(/^#\/?/, '').split('?'); const [name, ...params] = path.split('/');
  return { name, params, q: new URLSearchParams(qs || '') };
}

function chrome() {
  const w = ws.current, cur = location.hash.replace(/^#\/?/, '');
  const base = parse().name, q = parse().q;
  const isOn = href => { const [path, qs] = href.replace(/^#\//, '').split('?'); return path === base && (qs ? new URLSearchParams(qs).get('tab') === q.get('tab') : !q.get('tab')); };
  const side = document.getElementById('side');
  const item = ([i, title, sub, href]) => h('a', { class: 'nav-item' + (isOn(href) ? ' on' : ''), href: href.replace('#/#coverage', '#/'), 'aria-current': isOn(href) ? 'page' : null,
    onclick: e => { document.getElementById('app').classList.remove('menu-open'); if (href.endsWith('#coverage')) { e.preventDefault(); location.hash = '#/'; setTimeout(() => document.getElementById('coverage')?.scrollIntoView({ behavior: 'smooth' }), 300); } } },
    ic(i), h('span', { class: 'lbl' }, h('b', null, title), h('small', null, sub)));
  side.replaceChildren(
    h('div', { class: 'side-top' }, h('a', { class: 'mark', href: '../', title: 'AgroLand home' }, 'A'), h('div', { class: 'side-brand' }, h('strong', null, 'AgroLand'), h('small', null, 'Germany · India · preprod')),
      h('button', { class: 'icon-btn', 'aria-label': 'Close menu', onclick: () => document.getElementById('app').classList.remove('menu-open') }, '✕')),
    h('a', { class: 'side-new', href: '#/' }, ic('plus'), 'New check'),
    h('div', { class: 'side-scroll' }, NAV.map(([g, items]) => [g, items.filter(x => !x[4] || (x[4] === 'any' ? !!w : x[4] === w?.role))]).filter(([, items]) => items.length).map(([g, items]) => h('div', { class: 'side-group' }, h('div', { class: 'side-group-t' }, g), items.map(item)))),
    h('a', { class: 'side-user', href: '#/start' }, h('span', { class: 'avatar' }, (w?.name || '?')[0].toUpperCase()), h('span', { class: 'lbl' }, h('b', null, w ? w.name : 'No workspace'), h('small', null, w ? `${{ owner: 'Landowner', farm: 'Tenant farm', developer: 'Energy developer' }[w.role]} · ${w.country}${w.persona ? ' · demo' : ''}` : 'Create one to start')), h('span', { class: 'chev' }, '⇅')));
  const banner = document.getElementById('banner'), c = V.ctx.config;
  banner.hidden = c.payment_mode !== 'masumi' && !showDevNotices;
  banner.className = c.payment_mode === 'masumi' ? 'live' : 'dev';
  banner.textContent = c.payment_mode === 'masumi' ? `Cardano ${c.network} · test funds only (${c.token}) · every payment is a real preprod transaction` : 'UNPAID DEV MODE - orders are not paid and no Cardano transaction exists. Not for demos.';
  const search = h('input', { id: 'find', placeholder: 'Find a parcel by cadastral number ( / )', 'aria-label': 'Find a parcel by cadastral number' });
  search.addEventListener('keydown', e => { if (e.key === 'Enter' && search.value.trim()) location.hash = '#/map?find=' + encodeURIComponent(search.value.trim()); });
  const top = document.getElementById('top');
  top.replaceChildren(...[h('button', { class: 'icon-btn menu-btn', 'aria-label': 'Open menu', onclick: () => document.getElementById('app').classList.add('menu-open') }, ic('menu')), h('h1', null, ROUTES[base]?.title || ''), h('span', { class: 'grow' }),
    h('label', { class: 'search' }, ic('search'), search), !w && h('a', { class: 'btn primary sm', href: '#/start' }, 'Create workspace')].filter(Boolean));
}
addEventListener('keydown', e => { if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) { e.preventDefault(); document.getElementById('find')?.focus(); } });

let seq = 0;
async function route() {
  const my = ++seq, { name, params, q } = parse(), r = ROUTES[name] || ROUTES[''];
  chrome();
  const view = document.getElementById('view');
  view.replaceChildren(h('p', { class: 'muted' }, 'Loading…'));
  try {
    const node = await r.fn(q, params);
    if (my !== seq) return;
    view.replaceChildren(node); document.title = `${r.title} · AgroLand`;
  } catch (e) {
    if (my !== seq) return;
    view.replaceChildren(h('div', { class: 'callout bad' }, h('b', null, 'Something went wrong. '), e.message, h('p', { class: 'small' }, e instanceof ApiError && e.status === 401 ? 'Your workspace token is not valid here. ' : 'Your data is safe on the server; reload to try again. '), h('a', { class: 'btn sm', href: '#/start' }, 'Workspaces')));
  }
}

V.ctx.rerender = () => route();
try { V.ctx.config = await api('/config'); } catch { document.getElementById('view').textContent = 'The server is not reachable.'; throw new Error('no config'); }
addEventListener('hashchange', route);
route();
