// One Sokosumi Task = at most one AgroLand order. The gateway owns execution, the report and the Masumi seller side; this module only
// (1) creates the order, (2) hands the signed payment terms to Sokosumi Core as a `masumiPayment` task event (Core's buyer locks the funds),
// (3) waits until the gateway has the funds locked and the report delivered, (4) completes the Task with that exact text, (5) records the
// seller receipt. Every external write is journalled BEFORE it is sent; an uncertain write is never replayed.
import { writeFileSync, mkdirSync } from 'node:fs';
import { gateway } from './gateway.mjs';
import { verifySettlement } from './settlement.mjs';
import { loadSokosumiRuntime } from './sokosumi-runtime.mjs';
import { assertTaskTarget, verifyRuntimeTask, taskTarget } from './task-target.mjs';

export const stageTerminal = new Set(['settled', 'failed', 'quote-only']);

export async function createPaidAdapter({ save, paidEnabled, core: providedCore, target = taskTarget(), api = gateway, sellerAddress, unit }) {
  let core = providedCore;
  const getCore = async () => {
    if (!core) { const { readRuntimeCredential, createCoworkerHttpClient } = await loadSokosumiRuntime(); core = createCoworkerHttpClient({ apiKey: readRuntimeCredential(target.coworkerId) }); }
    return core;
  };
  const persist = async (task, state, paid) => { const next = { ...state, paid }; await save(task.id, next); return next; };
  const post = async (task, body) => (await verifyRuntimeTask(await getCore(), task.id, target)).post(`/v1/tasks/${encodeURIComponent(task.id)}/events`, body);

  return {
    /** Advances one step. `state.plan` must already hold an `order` plan. Returns the new state; `state.phase === 'completed'` when the Task is done. */
    async advance(task, state) {
      assertTaskTarget(task, target);
      let p = state.paid ?? {};
      if (!p.stage) {
        const plan = state.plan;
        if (!paidEnabled) return persist(task, state, { stage: 'quote-only', price: plan.price });
        state = await persist(task, state, { stage: 'order-pending', service: plan.service });
        const o = await api('/internal/orders', { method: 'POST', internal: true, body: { service: plan.service, country: plan.country, input: plan.input, external_ref: task.id, user_ref: task.id } });
        return persist(task, state, { stage: 'order-created', orderId: o.id, price: o.price.display });
      }
      if (p.stage === 'order-pending') throw new Error('Uncertain order creation. Inspect the gateway for external_ref ' + task.id + ' before recovery; automatic retry is disabled.');
      if (p.stage === 'order-created') {
        state = await persist(task, state, { ...p, stage: 'terms-pending' });
        await api(`/internal/orders/${p.orderId}/pay`, { method: 'POST', internal: true });
        return persist(task, state, { ...p, stage: 'terms-saved' });
      }
      if (p.stage === 'terms-pending') throw new Error('Uncertain payment-request creation. Inspect the order ' + p.orderId + ' before recovery.');
      if (p.stage === 'terms-saved') {
        const payload = await api(`/internal/orders/${p.orderId}/core-payload`, { internal: true });
        if (Date.now() >= Number(payload.payByTime)) throw new Error('Signed payment deadline expired');
        state = await persist(task, state, { ...p, stage: 'purchase-pending', payload });
        const res = await post(task, { comment: `Payment requested: ${p.price}.`, masumiPayment: payload });
        return persist(task, state, { ...p, payload, stage: 'awaiting-escrow', eventId: res.data?.id });
      }
      if (p.stage === 'purchase-pending') throw new Error('Uncertain payment event. Inspect the Task events before recovery.');
      if (p.stage === 'awaiting-escrow') {
        const o = await api(`/internal/orders/${p.orderId}`, { internal: true });
        if (o.state === 'failed' || o.state === 'expired') return persist(task, { ...state, phase: 'failed' }, { ...p, stage: 'failed', reason: o.error || o.state });
        if (o.state !== 'delivered') return persist(task, state, { ...p, observed: o.state, payment: o.payment });
        return persist(task, state, { ...p, stage: 'result-ready', result: o.markdown, resultHash: o.result_hash, payment: o.payment });
      }
      if (p.stage === 'result-ready') {
        state = await persist(task, state, { ...p, stage: 'complete-pending' });
        const res = await post(task, { status: 'COMPLETED', comment: p.result });
        return persist(task, { ...state, phase: 'completed' }, { ...p, stage: 'awaiting-withdrawal', completionEventId: res.data?.id });
      }
      if (p.stage === 'complete-pending') throw new Error('Uncertain completion event. Inspect the Task before recovery.');
      if (p.stage === 'awaiting-withdrawal') {
        const o = await api(`/internal/orders/${p.orderId}`, { internal: true });
        p = { ...p, payment: o.payment };
        if (!o.payment.settlement_tx) return persist(task, state, p);
        const observed = { blockchainIdentifier: o.payment.blockchain_identifier, TransactionHistory: [{ status: 'Confirmed', newOnChainState: 'Withdrawn', txHash: o.payment.settlement_tx }] };
        const evidence = await verifySettlement({ core: await verifyRuntimeTask(await getCore(), task.id, target), taskId: task.id, payment: observed, sellerAddress, unit });
        if (!evidence.verified) return persist(task, state, { ...p, settlement: evidence });
        mkdirSync('.local/evidence', { recursive: true, mode: 0o700 });
        writeFileSync(`.local/evidence/${task.id}.json`, JSON.stringify({ taskId: task.id, orderId: p.orderId, price: p.price, resultHash: p.resultHash, fundsLockedTx: o.payment.funds_locked_tx, resultHashTx: o.payment.result_hash_tx, settlementTx: evidence.txHash, sellerNetAtomicUnits: evidence.netAtomicUnits, method: evidence.method }, null, 2), { mode: 0o600 });
        return persist(task, state, { ...p, stage: 'settled', settlement: evidence });
      }
      return state;
    },
  };
}
