import test from 'node:test';
import assert from 'node:assert/strict';
import { parsePlan, plan, describePlan } from './planner.mjs';

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

test('comment replies are plain text and never claim an order was placed', () => {
  const t = describePlan({ action: 'order', summary: 'Land Audit of a wind site in Gujarat.', price: '1.00 tUSDM' });
  assert.match(t, /would order/); assert.match(t, /Nothing was run or charged/); assert.match(t, /new Task/);
  assert.equal(describePlan({ action: 'clarify', question: 'Which country?' }), 'Which country?');
  assert.equal(describePlan({ action: 'decline', reason: 'Out of scope.' }), 'Out of scope.');
  assert.match(describePlan({ action: 'info' }), /describe the site/);
});
