import { api, ws, h, chip, toast, ApiError } from './core.js';
import * as V from './views.js';

const ICONS = {
  home: 'M3 11l9-8 9 8M5 10v10h14V10', owner: 'M3 21V8l9-5 9 5v13M9 21v-7h6v7', farm: 'M4 20c0-6 3-11 8-14 5 3 8 8 8 14M12 20V9M8 14l4-3 4 3',
  developer: 'M12 3v18M3 12h18M7 7l10 10M17 7L7 17', map: 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14', orders: 'M5 4h14v16H5zM9 9h6M9 13h6M9 17h3',
};
const ROUTES = {
  '': { title: 'Agents', fn: V.home, nav: 'home' }, start: { title: 'Workspaces', fn: V.start, nav: 'home' }, owner: { title: 'Landowner', fn: V.owner, nav: 'owner' },
  farm: { title: 'Tenant farm', fn: V.farm, nav: 'farm' }, developer: { title: 'Energy developer', fn: V.developer, nav: 'developer' },
  map: { title: 'Map', fn: V.map, nav: 'map' }, orders: { title: 'Orders', fn: V.orders, nav: 'orders' },
};

function parse() {
  const [path, qs] = location.hash.replace(/^#\/?/, '').split('?'); const [name, ...params] = path.split('/');
  return { name, params, q: new URLSearchParams(qs || '') };
}

function chrome() {
  const w = ws.current, cur = ROUTES[parse().name]?.nav;
  const link = (key, label, href) => h('a', { href, class: cur === key ? 'on' : '', 'aria-current': cur === key ? 'page' : null }, h('span', { html: `<svg viewBox="0 0 24 24"><path d="${ICONS[key]}"/></svg>` }), label);
  const rail = document.getElementById('rail');
  rail.replaceChildren(h('a', { class: 'logo', href: '../', title: 'AgroLand home' }, 'A'), link('home', 'Agents', '#/'),
    ...(w ? [link(w.role, { owner: 'Owner', farm: 'Farm', developer: 'Developer' }[w.role], '#/' + w.role), link('map', 'Map', '#/map'), link('orders', 'Orders', '#/orders')] : []));
  const banner = document.getElementById('banner'), c = V.ctx.config;
  banner.className = c.payment_mode === 'masumi' ? 'live' : 'dev';
  banner.textContent = c.payment_mode === 'masumi' ? `Cardano ${c.network} · test funds only (${c.token}) · every payment is a real preprod transaction` : 'UNPAID DEV MODE - orders are not paid and no Cardano transaction exists. Not for demos.';
  const top = document.getElementById('top');
  top.replaceChildren(h('h1', null, ROUTES[parse().name]?.title || ''), h('span', { class: 'grow' }),
    w ? h('span', null, h('b', null, w.name), ' ', chip(`${w.role} · ${w.country}`, 'info'), w.persona ? chip(' demo', '') : null, ' ', h('a', { href: '#/start' }, 'switch')) : h('a', { class: 'btn primary sm', href: '#/start' }, 'Create workspace'));
}

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
