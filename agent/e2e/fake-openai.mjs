// TESTING STAND-IN for the language model: a tiny OpenAI-compatible /v1/chat/completions server with scripted behaviour.
// It lets us exercise the REAL Eve runtime, the REAL tools and the REAL gateway without a model key. It proves wiring, not model quality.
import { createServer } from 'node:http';

const last = (m, role) => [...m].reverse().find((x) => x.role === role);
const text = (c) => (typeof c === 'string' ? c : (c || []).map((p) => p.text || '').join(''));

function decide(body) {
  const msgs = body.messages;
  const tool = msgs[msgs.length - 1].role === 'tool' ? msgs[msgs.length - 1] : null;
  const user = text(last(msgs.filter((m) => m.role === 'user'), 'user')?.content || msgs.filter((m) => m.role === 'user').pop()?.content);
  if (tool) {
    const r = JSON.parse(text(tool.content).replace(/^[^{]*/, '') || '{}');
    const v = r.output ?? r.result ?? r;
    if (tool.name === 'validate_order' || true) {
      if (v.ok === false) return { content: JSON.stringify({ action: 'clarify', question: `I could not use that input: ${v.error}` }) };
      const m = user.match(/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/);
      const india = /india/i.test(user);
      return { content: JSON.stringify({ action: 'order', service: 'land_audit', country: india ? 'IN' : 'DE', input: { project_type: /wind/i.test(user) ? 'wind' : 'solar', lat: Number(m[1]), lon: Number(m[2]) }, summary: 'Audit the requested site.' }) };
    }
  }
  const m = user.match(/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/);
  if (!/MODE: PLAN/.test(user)) return { content: 'ok' };
  if (!m) return { content: JSON.stringify({ action: 'clarify', question: 'Where is the site (latitude, longitude) and in which country?' }) };
  const india = /india/i.test(user);
  return { tool: { name: 'validate_order', args: { service: 'land_audit', country: india ? 'IN' : 'DE', input: { project_type: /wind/i.test(user) ? 'wind' : 'solar', lat: Number(m[1]), lon: Number(m[2]) } } } };
}

export function startFakeModel(port) {
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const c of req) raw += c;
    if (req.method !== 'POST' || !req.url.endsWith('/chat/completions')) { res.writeHead(404); return res.end('{}'); }
    const body = JSON.parse(raw); const d = decide(body); const id = 'chatcmpl-fake';
    const delta = d.tool ? { role: 'assistant', tool_calls: [{ index: 0, id: 'call_' + Date.now(), type: 'function', function: { name: d.tool.name, arguments: JSON.stringify(d.tool.args) } }] } : { role: 'assistant', content: d.content };
    const finish = d.tool ? 'tool_calls' : 'stop';
    if (body.stream) {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      const chunk = (delta, fr) => `data: ${JSON.stringify({ id, object: 'chat.completion.chunk', created: 0, model: 'fake', choices: [{ index: 0, delta, finish_reason: fr }] })}\n\n`;
      res.write(chunk(delta, null)); res.write(chunk({}, finish));
      res.write(`data: ${JSON.stringify({ id, object: 'chat.completion.chunk', created: 0, model: 'fake', choices: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } })}\n\n`);
      return res.end('data: [DONE]\n\n');
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ id, object: 'chat.completion', created: 0, model: 'fake', choices: [{ index: 0, message: d.tool ? { role: 'assistant', content: null, tool_calls: delta.tool_calls } : { role: 'assistant', content: d.content }, finish_reason: finish }], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } }));
  });
  return new Promise((r) => server.listen(port, '127.0.0.1', () => r(server)));
}
