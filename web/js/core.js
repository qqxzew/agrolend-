// Small helpers shared by all views: DOM builder, API client with workspace tokens, formatting, toasts.
const LS = 'agroland.workspaces.v1';
export const ws = {
  read() { try { return JSON.parse(localStorage.getItem(LS)) || { list: [], current: null }; } catch { return { list: [], current: null }; } },
  write(v) { try { localStorage.setItem(LS, JSON.stringify(v)); } catch { /* private mode: workspace lives for this tab only */ mem = v; } },
  get current() { const s = this.read(); return s.list.find(w => w.id === s.current) || null; },
  add(user, token) { const s = this.read(); s.list = s.list.filter(w => w.id !== user.id).concat([{ ...user, token }]); s.current = user.id; this.write(s); },
  addQuiet(user, token) { const s = this.read(); s.list = s.list.filter(w => w.id !== user.id).concat([{ ...user, token }]); this.write(s); },
  use(id) { const s = this.read(); s.current = id; this.write(s); },
  drop(id) { const s = this.read(); s.list = s.list.filter(w => w.id !== id); if (s.current === id) s.current = s.list[0]?.id || null; this.write(s); },
};
let mem = null;

export class ApiError extends Error { constructor(status, detail) { super(typeof detail === 'string' ? detail : JSON.stringify(detail)); this.status = status; this.detail = detail; } }

export async function api(path, { method = 'GET', body, form, blob } = {}) {
  const headers = {}; const w = ws.current;
  if (w) headers.Authorization = 'Bearer ' + w.token;
  let payload;
  if (form) payload = form; else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  let r;
  try { r = await fetch('/api' + path.replace(/^\/api/, ''), { method, headers, body: payload }); }
  catch { throw new ApiError(0, 'The server is not reachable. Check your connection and try again.'); }
  if (r.status === 204) return null;
  if (blob) { if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => ({}))).detail || r.statusText); return r.blob(); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401 && w) { toast('Your workspace token is no longer valid on this server. Create a new workspace.', true); }
    const d = data.detail; throw new ApiError(r.status, Array.isArray(d) ? d.map(e => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join('; ') : d || r.statusText);
  }
  return data;
}

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v; else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v; else if (v === true) el.setAttribute(k, ''); else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const chip = (text, kind = '') => h('span', { class: 'chip ' + kind }, text);
export const fmtTime = iso => iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';
export const fmtMs = ms => ms ? new Date(Number(ms)).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';
export const num = (n, d = 2) => n == null ? '-' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d });
export const parcelLabel = label => String(label || '').replace(/\s*\(demo\)/gi, '').replace(/\s*\(illustrative\)/gi, '').trim();
export const money = (n, cur) => cur === 'INR' ? '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 }) : cur === 'EUR' ? '€' + Number(n).toLocaleString('en-GB', { maximumFractionDigits: 2 }) : num(n);

export function toast(msg, err = false) {
  let box = document.getElementById('toast'); if (!box) { box = h('div', { id: 'toast', role: 'status', 'aria-live': 'polite' }); document.body.append(box); }
  const t = h('div', { class: err ? 'err' : '' }, msg); box.append(t); setTimeout(() => t.remove(), err ? 7000 : 3500);
}
export async function guard(fn, btn) {
  if (btn) btn.disabled = true;
  try { return await fn(); } catch (e) { toast(e.message || String(e), true); } finally { if (btn) btn.disabled = false; }
}
export const download = (blob, name) => { const a = h('a', { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click(); a.remove(); };
export const copy = async t => { try { await navigator.clipboard.writeText(t); toast('Copied'); } catch { toast(t); } };
export const hash = t => h('span', { class: 'hash' }, t);
export const kv = rows => h('table', { class: 't' }, rows.filter(Boolean).map(([k, v]) => h('tr', null, h('th', null, k), h('td', null, v))));
export const field = (label, input, hint) => h('label', { class: 'f' }, label, input, hint && h('small', null, hint));
export const empty = text => h('div', { class: 'empty' }, text);
export const spinner = text => h('span', null, h('span', { class: 'spin' }), ' ', text || '');

// The red "UNPAID DEV MODE" notices are hidden for clean demos. Open the app with ?dev=1 (e.g. /app/?dev=1) to show them again; the mode itself is unchanged.
export const showDevNotices = (() => { try { return new URLSearchParams(location.search).has('dev'); } catch { return false; } })();
