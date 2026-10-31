// Registers the three AgroLand paid services in Masumi (one registry entry per agent) with fixed prices from ../config/services.json.
// Registration only writes metadata (and mints an NFT); it does not host or run anything: the gateway serves /masumi/<service>/ (MIP-003).
// Registry entries cannot be edited in place (changing price = deregister + register again), so check the prices before `register`.
//   node register-agents.mjs plan       print what would be sent, change nothing
//   node register-agents.mjs register   needs AUTHORIZATION from the team: spends test ADA, writes a public registry entry
//   node register-agents.mjs status     reads the registry, saves agent identifiers to docs/registration-state.json
import fs from 'node:fs';
import { requireAgentAuthor, v2FixedPricing } from './registration-config.mjs';

const mode = process.argv[2] || 'plan';
const catalog = JSON.parse(fs.readFileSync(new URL('../config/services.json', import.meta.url), 'utf8'));
const statePath = 'docs/registration-state.json';
const payment = fs.existsSync('docs/payment-state.json') ? JSON.parse(fs.readFileSync('docs/payment-state.json', 'utf8')) : null;
const state = fs.existsSync(statePath) ? JSON.parse(fs.readFileSync(statePath, 'utf8')) : { agents: {} };
state.agents ??= {};
const save = () => { fs.mkdirSync('docs', { recursive: true }); fs.writeFileSync(statePath, JSON.stringify(state, null, 2)); };
const base = (process.env.MPS_URL || '') + '/api/v1';
const headers = { token: process.env.ADMIN_KEY, 'content-type': 'application/json' };
async function request(path, body) {
  const r = await fetch(base + path, { headers, method: body ? 'POST' : 'GET', body: body ? JSON.stringify(body) : undefined });
  const j = await r.json(); if (!r.ok || j.status !== 'success') throw Error(`${r.status}: ${JSON.stringify(j.error ?? j.message ?? {})}`); return j.data;
}
const publicBase = (process.env.PUBLIC_BASE_URL || '').replace(/\/$/, '');
const tags = { land_audit: ['land', 'wind', 'solar', 'germany', 'india', 'due-diligence'], lease_check: ['farm', 'lease', 'germany', 'india'], pool_access: ['energy', 'pooling', 'nda', 'germany', 'india'] };

function body(service, sellingWalletVkey, address) {
  const s = catalog.services[service];
  return {
    network: catalog.payment.network, type: 'Standard', sellingWalletVkey,
    supportedPaymentSources: [{ chain: 'Cardano', network: catalog.payment.network, paymentSourceType: catalog.payment.paymentSourceType, address,
      pricing: v2FixedPricing(catalog.payment.token, s.price.amount) }],
    ExampleOutputs: [], Tags: tags[service], name: `AgroLand ${s.title}`, description: s.summary,
    Capability: { name: `agroland-${service}`, version: '1' }, Author: { name: requireAgentAuthor(process.env.AGENT_AUTHOR) },
    apiBaseUrl: `${publicBase}/masumi/${service}`,
  };
}

if (mode === 'plan') {
  for (const k of Object.keys(catalog.services)) console.log(k, JSON.stringify(body(k, '<sellingWalletVkey>', '<paymentSourceAddress>'), null, 1));
} else if (mode === 'register') {
  if (!publicBase.startsWith('https://')) throw Error('PUBLIC_BASE_URL must be the public https URL of the AgroLand gateway');
  if (!payment) throw Error('docs/payment-state.json (sourceId, walletId, sellerAddress) is missing: set up the payment service first');
  const wallet = await request(`/wallet?walletType=Selling&id=${payment.walletId}`);
  const sources = await request('/payment-source?take=100');
  const find = (x) => { if (Array.isArray(x)) { for (const y of x) { const r = find(y); if (r) return r; } } else if (x && typeof x === 'object') { if (x.id === payment.sourceId) return x; for (const y of Object.values(x)) { const r = find(y); if (r) return r; } } };
  const source = find(sources);
  if (!source || wallet.walletAddress !== payment.sellerAddress) throw Error('Dedicated source or wallet mismatch');
  for (const service of Object.keys(catalog.services)) {
    const a = state.agents[service] ??= {};
    if (a.registrationId) { console.log(service, 'already registered', a.registrationId); continue; }
    if (a.writePending) throw Error(`Previous registration write for ${service} is uncertain: inspect the registry before retry`);
    a.writePending = true; a.request = body(service, wallet.walletVkey, source.smartContractAddress); save();   // journal before the write
    const r = await request('/registry', a.request);
    a.registrationId = r.id; a.writePending = false; a.registration = r; save(); console.log(service, 'registration submitted', r.id);
  }
  state.sellerVkey = wallet.walletVkey; state.sellerAddress = payment.sellerAddress; state.supportedPaymentSourceIndex = 0; save();
} else {
  const r = await request(`/registry?network=${catalog.payment.network}&filterPaymentSourceType=${catalog.payment.paymentSourceType}&limit=100`);
  const walk = (x, f) => { if (Array.isArray(x)) x.forEach((y) => walk(y, f)); else if (x && typeof x === 'object') { f(x); Object.values(x).forEach((y) => walk(y, f)); } };
  for (const [service, a] of Object.entries(state.agents)) walk(r, (x) => { if (x.id === a.registrationId) { a.registration = x; a.agentIdentifier = x.agentIdentifier; a.state = x.state; } });
  save();
  for (const [service, a] of Object.entries(state.agents)) console.log(service, a.state ?? 'not found', a.agentIdentifier ?? '');
  console.log('\nPut these into the gateway .env:');
  for (const [service, a] of Object.entries(state.agents)) if (a.agentIdentifier) console.log(`AGENT_IDENTIFIER_${service.toUpperCase()}=${a.agentIdentifier}`);
  if (state.sellerVkey) console.log(`SELLER_VKEY=${state.sellerVkey}`);
}
