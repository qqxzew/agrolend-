import test from 'node:test';
import assert from 'node:assert/strict';
import { parsePlan, plan } from './planner.mjs';

test('parsePlan extracts JSON from model text and rejects incomplete orders', () => {
  assert.equal(parsePlan('Sure!\n{"action":"clarify","question":"Which country?"}').action, 'clarify');
  assert.throws(() => parsePlan('no json here'));
  assert.throws(() => parsePlan('{"action":"order","service":"land_audit","country":"FR","input":{}}'));
  assert.throws(() => parsePlan('{"action":"delete_everything"}'));
});

test('an order plan is re-validated by the gateway before use', async () => {
  const ask = async () => '{"action":"order","service":"land_audit","country":"DE","input":{"lat":10,"lon":10,"project_type":"solar"}}';
  const bad = await plan('x', 'j', { ask, check: async () => ({ ok: false, error: 'The point is outside Germany' }) });
  assert.equal(bad.action, 'clarify');
  assert.match(bad.question, /outside Germany/);
  const good = await plan('x', 'j', { ask, check: async () => ({ ok: true, price: '1.00 tUSDM', subject: 'Point' }) });
  assert.equal(good.action, 'order');
  assert.equal(good.price, '1.00 tUSDM');
});
