// Sokosumi Coworker worker for AgroLand. Polls Tasks assigned to the Coworker and, per Task:
//   1. starts it (runtime start),   2. lets the language model plan it (planner.mjs; tools: coverage, validate_order),
//   3a. clarify / decline / info / quote-only  -> completes with the model's answer (execution-only, no payment)
//   3b. order -> one paid AgroLand order via the gateway, paid through Sokosumi Core (paid-order.mjs), completed with the hash-bound report,
//   4. posts an AI summary as a follow-up comment (NOT part of the hashed deliverable) and answers later comments.
import { runSokosumi } from './sokosumi-cli.mjs';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { acquireWorkerLock } from './worker-lock.mjs';
import { client } from './client.mjs';
import { plan, summarize, describePlan } from './planner.mjs';
import { createPaidAdapter } from './paid-order.mjs';
import { taskTarget, isTaskForTarget } from './task-target.mjs';
import { loadSokosumiRuntime } from './sokosumi-runtime.mjs';
import { gateway } from './gateway.mjs';
import { readRuntimeKey, runtimeCliOptions, runtimeKeyFile } from './runtime-key.mjs';

const target = taskTarget();
const id = target.coworkerId;
mkdirSync('.local', { recursive: true, mode: 0o700 });
const releaseLock = acquireWorkerLock();
process.once('exit', releaseLock);
for (const s of ['SIGINT', 'SIGTERM']) process.once(s, () => { releaseLock(); process.exit(0); });
const sokosumiRuntime = await loadSokosumiRuntime();
const { createCoworkerHttpClient, fetchTaskEvents, createTaskEvent, fetchTasks } = sokosumiRuntime;
const runtimeApiKey = readRuntimeKey(id, sokosumiRuntime);
const runtime = createCoworkerHttpClient({ apiKey: runtimeApiKey });
const cli = (args) => {
  const o = runtimeCliOptions(args, runtimeApiKey);
  return JSON.parse(runSokosumi(['--preprod', ...o.args, '--json'], { encoding: 'utf8', timeout: 30000, maxBuffer: 4 * 1024 * 1024, input: o.input }));
};
// With a key file there is no user sign-in on the host: list the Coworker's own Tasks with its key instead of `tasks list`.
const listTasks = async () => (runtimeKeyFile()
  ? (await fetchTasks(runtime, { coworkerId: id }, AbortSignal.timeout(30000))).tasks
  : cli(['tasks', 'list', '--coworker-id', id, ...target.taskArgs]).tasks);
const paidEnabled = process.env.PAID_TASKS_ENABLED === 'true';
const unit = JSON.parse(readFileSync(new URL('../config/services.json', import.meta.url), 'utf8')).payment.token.unit;
const registration = () => (existsSync('docs/registration-state.json') ? JSON.parse(readFileSync('docs/registration-state.json', 'utf8')) : {});
await client.health();
const jpath = (t) => `.local/${t}.json`;
const paid = await createPaidAdapter({ target, paidEnabled, core: runtime, save: async (t, s) => writeFileSync(jpath(t), JSON.stringify(s), { mode: 0o600 }), sellerAddress: registration().sellerAddress, unit });
const quote = (p) => `AgroLand would run **${p.service === 'land_audit' ? 'Land Audit' : 'Lease Check'}** for ${p.subject} (${p.country}). ${p.summary || ''}\n\nPrice: **${p.price}** on Cardano preprod (test funds). Paid Tasks are not enabled on this worker, so nothing was run or charged. This answer is execution-only.`;

function completeText(t, text, state) {
  writeFileSync(`.local/${t.id}.txt`, text, { mode: 0o600 });
  writeFileSync(jpath(t.id), JSON.stringify({ ...state, phase: 'complete-pending' }), { mode: 0o600 });
  const done = cli(['runtime', 'complete', t.id, ...target.runtimeArgs, '--coworker-id', id, '--result-file', `.local/${t.id}.txt`]);
  writeFileSync(jpath(t.id), JSON.stringify({ ...state, phase: 'completed', completion: done }), { mode: 0o600 });
  console.log('Completed', t.id);
}

async function follow(t, state) {
  const f = `.local/${t.id}-comments.json`;
  const done = existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) : {};
  if (state.paid?.orderId && !done.summary && state.paid.stage !== 'order-created') {
    try { const s = await summarize(state.paid.orderId, `.local/${t.id}-summary.json`); await createTaskEvent(runtime, t.id, { comment: `AI summary (not part of the hashed deliverable):\n\n${s}` }, AbortSignal.timeout(30000)); done.summary = 'posted'; writeFileSync(f, JSON.stringify(done), { mode: 0o600 }); } catch (e) { console.error('Summary failed', t.id, e.message.slice(0, 160)); }
  }
  const { events } = await fetchTaskEvents(runtime, t.id, AbortSignal.timeout(30000));
  for (const e of events.filter((x) => x.actor?.type === 'user' && typeof x.comment === 'string' && x.comment.trim())) {
    if (done[e.id]) continue;
    done[e.id] = 'pending'; writeFileSync(f, JSON.stringify(done), { mode: 0o600 });
    const journal = `.local/${t.id}-reply-${e.id}.json`;
    let reply;
    if (state.paid?.orderId) {
      const { answer } = await import('./client.mjs');
      reply = await answer(`MODE: SUMMARIZE\n\nOrder id: ${state.paid.orderId}\nThe customer asks: ${e.comment.slice(0, 4000)}`, journal);
    } else reply = describePlan(await plan(e.comment.slice(0, 4000), journal));
    await createTaskEvent(runtime, t.id, { comment: reply }, AbortSignal.timeout(30000));
    done[e.id] = 'posted'; writeFileSync(f, JSON.stringify(done), { mode: 0o600 });
  }
}

console.log('Continuous worker running', process.pid, paidEnabled ? '(paid tasks ENABLED)' : '(paid tasks disabled: execution-only)');
while (true) {
  try {
    for (const t of (await listTasks()).filter((x) => isTaskForTarget(x, target))) {
      try {
        let state = existsSync(jpath(t.id)) ? JSON.parse(readFileSync(jpath(t.id), 'utf8')) : {};
        if (t.status === 'READY' && !state.phase) {
          writeFileSync(jpath(t.id), JSON.stringify({ phase: 'starting' }), { mode: 0o600 });
          const started = cli(['runtime', 'start', t.id, ...target.runtimeArgs, '--coworker-id', id]);
          state = { phase: 'started', input: started.description }; writeFileSync(jpath(t.id), JSON.stringify(state), { mode: 0o600 });
        }
        if (state.phase === 'started') {
          writeFileSync(jpath(t.id), JSON.stringify({ ...state, phase: 'planning' }), { mode: 0o600 });
          const p = await plan(state.input, `.local/${t.id}-session.json`);
          state = { ...state, phase: 'planned', plan: p }; writeFileSync(jpath(t.id), JSON.stringify(state), { mode: 0o600 });
        }
        if (state.phase === 'planned' || state.phase === 'ordering') {
          const p = state.plan;
          if (p.action !== 'order') completeText(t, p.question || p.reason || p.answer, state);
          else if (!paidEnabled) { state = await paid.advance(t, { ...state, phase: 'ordering' }); completeText(t, quote(p), state); }
          else state = await paid.advance(t, { ...state, phase: 'ordering' });
        }
        if (state.phase === 'completed' && state.paid && !['settled', 'failed', 'quote-only'].includes(state.paid.stage)) state = await paid.advance(t, state);
        if (state.phase === 'completed') await follow(t, state);
      } catch (e) { console.error('Task blocked', t.id, String(e.message).slice(0, 240)); }
    }
  } catch (e) { console.error('Polling read failed', String(e.message).slice(0, 200)); }
  await new Promise((r) => setTimeout(r, 5000));
}
