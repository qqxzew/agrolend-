// Minimal client for the AgroLand gateway (the same execution system the website uses).
const base = () => (process.env.AGROLAND_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');
export class GatewayError extends Error { constructor(status, detail) { super(`gateway ${status}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`.slice(0, 400)); this.status = status; this.detail = detail; } }
export async function gateway(path, { method = 'GET', body, internal = false, fetchImpl = fetch } = {}) {
  const headers = { 'content-type': 'application/json' };
  if (internal) { const k = process.env.AGROLAND_INTERNAL_KEY; if (!k) throw new Error('AGROLAND_INTERNAL_KEY is not set'); headers['x-internal-key'] = k; }
  const r = await fetchImpl(base() + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(60000) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new GatewayError(r.status, data.detail ?? data);
  return data;
}
