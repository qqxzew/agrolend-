// State-machine tests with a FAKE gateway and a FAKE Sokosumi Core: they prove journalling and no-replay rules, not a real payment.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createPaidAdapter } from './paid-order.mjs';

const target = { coworkerId: 'cw1', organizationId: null, taskArgs: [], runtimeArgs: ['--personal'] };
const task = { id: 'task1', coworkerId: 'cw1', organizationId: null };
const plan = { action: 'order', service: 'lease_check', country: 'IN', input: { source: 'demo' }, price: '2.00 tUSDM', subject: 'Farm' };

function harness({ paidEnabled = true, orderStates = [] } = {}) {
  const calls = [], saved = [], events = [];
  const api = async (path, opts = {}) => {
    calls.push(`${opts.method || 'GET'} ${path}`);
    if (path === '/internal/orders') return { id: 'o1', price: { display: '2.00 tUSDM' } };
    if (path === '/internal/orders/o1/pay') return {};
    if (path === '/internal/orders/o1/core-payload') return { blockchainIdentifier: 'bc', payByTime: String(Date.now() + 600000) };
    if (path === '/internal/orders/o1') { const s = orderStates.shift() || 'delivered'; return { state: s, markdown: '# Report', result_hash: 'h', payment: { blockchain_identifier: 'bc', funds_locked_tx: 'tx1' } }; }
    throw new Error('unexpected ' + path);
  };
  const core = { get: async (p) => (p.endsWith('/receipt') ? { data: { settled: false } } : { data: task }), post: async (p, body) => { events.push(body); return { data: { id: 'ev' + events.length } }; } };
  return { calls, saved, events, make: () => createPaidAdapter({ save: async (id, s) => saved.push(JSON.parse(JSON.stringify(s))), paidEnabled, core, target, api, sellerAddress: 'addr', unit: 'u' }) };
}

test('paid flow: order -> payment request -> Core payment event -> wait -> complete with the exact report', async () => {
  const h = harness({ orderStates: ['awaiting_payment'] });
  const a = await h.make();
  let s = { phase: 'ordering', plan };
  const stages = [];
  for (let i = 0; i < 8 && s.paid?.stage !== 'awaiting-withdrawal'; i++) { s = await a.advance(task, s); stages.push(s.paid.stage); }
  assert.deepEqual(stages, ['order-created', 'terms-saved', 'awaiting-escrow', 'awaiting-escrow', 'result-ready', 'awaiting-withdrawal']);
  assert.equal(h.events[0].masumiPayment.blockchainIdentifier, 'bc');
  assert.equal(h.events[1].status, 'COMPLETED');
  assert.equal(h.events[1].comment, '# Report', 'the Task result is exactly the hashed text');
  assert.equal(h.calls.filter((c) => c === 'POST /internal/orders').length, 1);
  assert.equal(s.phase, 'completed');
});

test('execution-only when paid tasks are disabled: no order is created', async () => {
  const h = harness({ paidEnabled: false });
  const s = await (await h.make()).advance(task, { phase: 'ordering', plan });
  assert.equal(s.paid.stage, 'quote-only');
  assert.deepEqual(h.calls, []);
});

test('an uncertain write is never replayed', async () => {
  const h = harness();
  const a = await h.make();
  await assert.rejects(a.advance(task, { phase: 'ordering', plan, paid: { stage: 'order-pending' } }), /Uncertain order creation/);
  await assert.rejects(a.advance(task, { phase: 'ordering', plan, paid: { stage: 'terms-pending', orderId: 'o1' } }), /Uncertain payment-request/);
  await assert.rejects(a.advance(task, { phase: 'ordering', plan, paid: { stage: 'purchase-pending' } }), /Uncertain payment event/);
  await assert.rejects(a.advance(task, { phase: 'ordering', plan, paid: { stage: 'complete-pending' } }), /Uncertain completion/);
  assert.deepEqual(h.calls, []);
});

test('a task for another coworker is rejected', async () => {
  const a = await harness().make();
  await assert.rejects(a.advance({ ...task, coworkerId: 'other' }, { plan }), /Coworker/);
});
