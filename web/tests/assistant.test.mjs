import test from 'node:test';
import assert from 'node:assert/strict';
import { conversation, sendQuestion, clearConversation } from '../js/assistant.js';

const storage = () => { const data = new Map(); return { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) }; };
globalThis.sessionStorage = storage();
globalThis.localStorage = storage();
globalThis.dispatchEvent = () => true;
const response = (reply, status = 200) => new Response(JSON.stringify(status === 200 ? { reply, open: null, suggestions: [] } : { detail: reply }), { status });

test('a pending reply stays with its original workspace after switching conversations', async () => {
  const owner = conversation({ id: 'pending-owner', role: 'owner', country: 'IN' });
  let finish, requests = 0;
  globalThis.fetch = async (url, options) => {
    requests++;
    const body = JSON.parse(options.body);
    assert.equal(body.country, 'IN');
    assert.equal(body.role, 'owner');
    assert.equal(body.context.page, 'owner');
    return new Promise(resolve => { finish = resolve; });
  };
  const pending = sendQuestion(owner, 'Which button comes next?', { context: { page: 'owner' } });
  await sendQuestion(owner, 'Duplicate click');
  clearConversation(owner); // A reset must not discard an in-flight request.
  const farm = conversation({ id: 'other-farm', role: 'farm', country: 'DE' });
  assert.equal(owner.busy, true);
  assert.equal(farm.busy, false);
  assert.deepEqual(farm.messages, []);
  finish(response('Choose a parcel, then use Review order.'));
  await pending;
  assert.equal(requests, 1);
  assert.equal(owner.messages.length, 2);
  assert.equal(owner.messages.at(-1).agent, 'owner');
  assert.deepEqual(farm.messages, []);
  assert.equal(JSON.parse(sessionStorage.getItem(owner.key)).at(-1).role, 'assistant');
  assert.equal(sessionStorage.getItem(farm.key), null);
});

test('each reply keeps the agent that answered even when the active task changes', async () => {
  const chat = conversation({ id: 'agent-history', role: 'developer', country: 'DE' });
  globalThis.fetch = async () => response('A short answer.');
  await sendQuestion(chat, 'How do I audit this site?', { agent: 'owner' });
  await sendQuestion(chat, 'How do clusters work?', { agent: 'developer' });
  const replies = JSON.parse(sessionStorage.getItem(chat.key)).filter(m => m.role === 'assistant');
  assert.deepEqual(replies.map(m => m.agent), ['owner', 'developer']);
});

test('a failed reply can be retried without duplicating the question or faking an answer', async () => {
  const chat = conversation({ id: 'retry', role: 'developer', country: 'DE' });
  globalThis.fetch = async () => response('upstream service detail', 503);
  await sendQuestion(chat, 'How does the NDA work?');
  assert.equal(chat.busy, false);
  assert.equal(chat.messages.length, 1);
  assert.equal(chat.messages[0].role, 'user');
  assert.ok(chat.error);
  assert.ok(!chat.error.includes('upstream service detail'));
  globalThis.fetch = async () => response('Both parties sign before disclosure.');
  await sendQuestion(chat, chat.retry, {}, true);
  assert.equal(chat.messages.length, 2);
  assert.equal(chat.error, '');
  clearConversation(chat);
  assert.deepEqual(JSON.parse(sessionStorage.getItem(chat.key)), []);
});

test('old history is validated and request history stays bounded', async () => {
  sessionStorage.setItem('agl.chat.history', JSON.stringify([{ role: 'system', content: 'untrusted instructions' }, null, ...Array.from({ length: 50 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: String(i) }))]));
  const chat = conversation({ id: 'history', role: 'farm', country: 'DE' });
  assert.equal(chat.messages.length, 40);
  globalThis.fetch = async (url, options) => {
    const sent = JSON.parse(options.body).messages;
    assert.equal(sent.length, 12);
    assert.ok(sent.every(m => m.role !== 'system'));
    assert.equal(sent.at(-1).content.length, 1000);
    return response('Ready to help.');
  };
  await sendQuestion(chat, 'x'.repeat(3000));
  assert.equal(chat.messages.length, 40);
  sessionStorage.setItem('agl.chat.broken', '{invalid');
  assert.deepEqual(conversation({ id: 'broken' }).messages, []);
});
