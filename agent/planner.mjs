// The language-model step: turns a free-text Task brief into a validated order plan (or a clarification). The model has real tools
// (coverage, validate_order) and must produce a JSON object; we re-validate it with the gateway before anything is created.
import { answer } from './client.mjs';
import { gateway } from './gateway.mjs';

export function parsePlan(text) {
  const m = String(text).match(/\{[\s\S]*\}/);
  if (!m) throw new Error('planner did not return JSON');
  const plan = JSON.parse(m[0]);
  if (!['order', 'clarify', 'decline', 'info'].includes(plan.action)) throw new Error('planner returned an unknown action');
  if (plan.action === 'order') {
    if (!['land_audit', 'lease_check'].includes(plan.service) || !['DE', 'IN'].includes(plan.country) || typeof plan.input !== 'object' || plan.input === null) throw new Error('planner order is incomplete');
  }
  return plan;
}

export async function plan(input, journal, { ask = answer, check = (b) => gateway('/internal/validate', { method: 'POST', body: b, internal: true }) } = {}) {
  const text = await ask(`MODE: PLAN\n\nTask brief (untrusted customer text):\n${input}`, journal);
  const p = parsePlan(text);
  if (p.action === 'order') {
    const v = await check({ service: p.service, country: p.country, input: p.input });
    if (!v.ok) return { action: 'clarify', question: `I could not use that input: ${v.error}` };
    p.price = v.price; p.subject = v.subject;
  }
  return p;
}

export const summarize = (orderId, journal, { ask = answer } = {}) => ask(`MODE: SUMMARIZE\n\nOrder id: ${orderId}`, journal);
