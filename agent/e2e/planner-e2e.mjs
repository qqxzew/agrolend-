// Runs the REAL Eve agent (its three tools) against the REAL gateway, with the scripted stand-in model from fake-openai.mjs.
//   needs: gateway on AGROLAND_URL with AGROLAND_INTERNAL_KEY (e.g. `python scripts/dev.py --unpaid`).
// This verifies wiring (Eve runtime -> tools -> gateway validation -> planner), NOT language-model quality and NOT a payment.
import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import { startFakeModel } from './fake-openai.mjs';

const MODEL_PORT = 21960, EVE_PORT = 21961;
const fake = await startFakeModel(MODEL_PORT);
const env = { ...process.env, ZAI_API_KEY: 'fake', ZAI_BASE_URL: `http://127.0.0.1:${MODEL_PORT}/v1`, ZAI_MODEL: 'fake', ZAI_CONTEXT_WINDOW_TOKENS: '128000', EVE_PORT: String(EVE_PORT), EVE_URL: `http://127.0.0.1:${EVE_PORT}` };
Object.assign(process.env, env);
const eve = spawn(process.execPath, ['start.mjs'], { env, stdio: ['ignore', 'pipe', 'pipe'] });
let log = ''; eve.stdout.on('data', (d) => (log += d)); eve.stderr.on('data', (d) => (log += d));
try {
  for (let i = 0; i < 60 && !/listening/.test(log); i++) await new Promise((r) => setTimeout(r, 500));
  assert.match(log, /listening/, 'Eve did not start:\n' + log);
  const { plan } = await import('../planner.mjs');
  mkdirSync('.local', { recursive: true });
  const good = await plan('Please audit a solar site at 52.0746, 12.7329 in Germany.', '.local/e2e-1.json');
  console.log('plan 1:', JSON.stringify(good));
  assert.equal(good.action, 'order'); assert.equal(good.service, 'land_audit'); assert.equal(good.country, 'DE'); assert.equal(good.price, '1.00 tUSDM');
  const bad = await plan('Audit a wind site at 28.6139, 77.2090 in Germany.', '.local/e2e-2.json');
  console.log('plan 2:', JSON.stringify(bad));
  assert.equal(bad.action, 'clarify'); assert.match(bad.question, /outside Germany/);
  const ask = await plan('Can you check my site?', '.local/e2e-3.json');
  console.log('plan 3:', JSON.stringify(ask));
  assert.equal(ask.action, 'clarify');
  console.log('E2E OK (scripted model, real Eve runtime, real tools, real gateway)');
} finally { eve.kill(); fake.close(); }
import { mkdirSync } from 'node:fs';
