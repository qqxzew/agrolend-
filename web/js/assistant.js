import { api, ws, h, spinner } from './core.js';
import { AVATAR } from './avatars.js';

// The home chat and the workspace companion use the same conversation. Capture
// its key before a request so switching workspaces cannot move a pending reply.
const conversations = new Map();
const changed = () => dispatchEvent(new Event('agl:chat'));
export function conversation(workspace = ws.current) {
  const key = 'agl.chat.' + (workspace?.id || 'none');
  if (!conversations.has(key)) {
    let messages = [];
    try { const saved = JSON.parse(sessionStorage.getItem(key)); if (Array.isArray(saved)) messages = saved.filter(m => ['user', 'assistant'].includes(m?.role) && typeof m.content === 'string').slice(-40); } catch {}
    conversations.set(key, { key, role: workspace?.role, country: workspace?.country, messages, busy: false, error: '', retry: '', draft: '' });
  }
  return conversations.get(key);
}
function save(chat) {
  chat.messages = chat.messages.slice(-40);
  try { sessionStorage.setItem(chat.key, JSON.stringify(chat.messages)); } catch {}
  changed();
}
export function clearConversation(chat) {
  if (chat.busy) return;
  chat.messages = []; chat.error = ''; chat.retry = ''; save(chat);
}
export async function sendQuestion(chat, question, options = {}, retry = false) {
  const content = String(question || '').trim().slice(0, 1000);
  if (!content || chat.busy) return;
  chat.busy = true; chat.error = ''; chat.retry = content;
  if (!retry || chat.messages.at(-1)?.role !== 'user' || chat.messages.at(-1)?.content !== content) chat.messages.push({ role: 'user', content });
  save(chat);
  try {
    const r = await api('/chat', { method: 'POST', body: { messages: chat.messages.slice(-12).map(({ role, content }) => ({ role, content })), role: chat.role, country: chat.country, ...options } });
    chat.messages.push({ role: 'assistant', content: r.reply, open: r.open, suggestions: r.suggestions || [] });
  } catch (e) {
    chat.error = e.status === 429 ? e.message : 'The assistant could not reply. Please try again. You can keep working on this page.';
  } finally { chat.busy = false; save(chat); }
}
export function openAssistantPage(page) {
  if (!['owner', 'farm', 'developer', 'orders', 'data'].includes(page)) return;
  location.hash = !['owner', 'farm', 'developer'].includes(page) || ws.current?.role === page ? '#/' + page : '#/start?role=' + page;
}

const ACTION = { owner: 'Open Land Audit', farm: 'Open Lease Check', developer: 'Open Pool Access', orders: 'Open my orders', data: 'Open data and sources' };
const SCREENS = {
  owner: ['Land Audit', "Let’s check your parcel", 'I can guide you from choosing a parcel to understanding your audit and publishing a listing.', ['How do I choose a parcel?', 'What does the audit check?', 'How do I publish a listing?']],
  farm: ['Lease Check', 'Make sense of your leases', 'Get help with your files, rent findings, crop status and your next steps.', ['Which files do I need?', 'What do the findings mean?', 'How do I record savings?']],
  developer: ['Site audit & Pool Access', 'Plan your next step', 'I can help with site audits, finding neighbours and the steps before a joint project.', ['How do I audit a site?', 'How does pooling work?', 'When is a site disclosed?']],
  orders: ['Orders', 'Understand your order', 'Ask about reports, payment stages or what happens next.', ['How do I open my report?', 'What do payment stages mean?', 'How do I verify a result?']],
  data: ['Data and sources', 'Know what’s behind the result', 'Explore coverage, source quality and what AgroLand can check.', ['Which sources do you use?', 'What does incomplete data mean?', 'Is ownership verified?']],
  map: ['Parcel map', 'Find your starting point', 'Get help choosing a parcel or drawing an outline for an audit.', ['How do I select a parcel?', 'Can I draw my own outline?', 'Which countries are covered?']],
  start: ['New workspace', 'A little help getting started', 'Choose the workspace that fits the work you want to do.', ['Which workspace should I choose?', 'Can I use different roles?', 'How is my workspace saved?']],
};
const TABS = { audit: 'Audit a parcel', listings: 'My listings', sites: 'Sites', deals: 'Matches & deals', market: 'Owner listings' };
const TAB_SCREENS = {
  'owner.listings': ['My listings', 'Publish on your terms', 'Get help with listings, consent and deciding when to share a boundary.', ['How do I publish a listing?', 'Who can see my boundary?', 'Can I withdraw a listing?']],
  'developer.deals': ['Matches & deals', 'From match to introduction', 'I can explain consent, payment and the NDA before either site is disclosed.', ['What happens after a match?', 'When do both parties sign?', 'When are site details shared?']],
  'developer.market': ['Owner listings', 'Find a parcel to lease', 'Get help with owner listings and requesting access to an exact boundary.', ['How do I request a boundary?', 'What can I see before consent?', 'Is ownership verified?']],
};

export function mountAssistant() {
  const app = document.getElementById('app'), panel = document.getElementById('assistant'), view = document.getElementById('view');
  const narrow = matchMedia('(max-width: 1100px)');
  let page = '', chat = conversation(), signature = '', lastFocus = null;
  const context = () => { const root = view.firstElementChild; return { page, tab: root?.dataset.assistantTab, stage: root?.dataset.assistantStage }; };
  const avatar = () => h('span', { class: 'agent-dot', 'aria-hidden': 'true', html: AVATAR[['owner', 'farm', 'developer'].includes(page) ? page : 'guide'] });
  const screenLabel = h('span', { class: 'assistant-screen' });
  const intro = h('div', { class: 'assistant-intro' });
  const log = h('div', { class: 'assistant-log', role: 'log', 'aria-label': 'Conversation with AgroLand assistant', 'aria-live': 'polite', 'aria-relevant': 'additions text', tabindex: 0 });
  const suggestions = h('div', { class: 'assistant-suggestions', 'aria-label': 'Suggested questions' });
  const error = h('div', { class: 'chat-error', role: 'status', hidden: true });
  const input = h('textarea', { rows: 2, maxlength: 1000, placeholder: 'Ask about this step…', 'aria-label': 'Message the AgroLand assistant', oninput: () => { chat.draft = input.value; } });
  const send = h('button', { class: 'send', type: 'submit', 'aria-label': 'Send message' }, '↑');
  const reset = h('button', { class: 'icon-btn', title: 'Start a new conversation', 'aria-label': 'Start a new conversation', onclick: () => clearConversation(chat) }, '↺');
  const launcher = h('button', { class: 'btn sm assistant-toggle', 'aria-controls': 'assistant', 'aria-expanded': 'false', onclick: () => setOpen(true) }, h('span', { class: 'assistant-spark', 'aria-hidden': 'true' }, '✦'), 'Ask AI');
  const close = h('button', { class: 'icon-btn assistant-close', 'aria-label': 'Close assistant', onclick: () => setOpen(false) }, '×');
  const scrim = h('div', { class: 'assistant-scrim', hidden: true, onclick: () => setOpen(false) });
  panel.before(scrim);
  panel.replaceChildren(
    h('div', { class: 'assistant-head' }, h('span', { class: 'assistant-mark', 'aria-hidden': 'true', html: AVATAR.guide }), h('div', { class: 'lbl' }, h('b', { id: 'assistant-title' }, 'AgroLand assistant'), h('small', null, 'A hand with every step')), reset, close),
    h('div', { class: 'assistant-context' }, h('span', { class: 'assistant-context-dot', 'aria-hidden': 'true' }), screenLabel, h('span', { class: 'assistant-ai' }, 'AI')),
    log, suggestions, error,
    h('form', { class: 'assistant-composer', onsubmit: e => { e.preventDefault(); ask(); } }, input,
      h('div', { class: 'composer-row' }, h('span', { class: 'small muted' }, 'Ask in your language'), h('span', { class: 'grow' }), send)),
    h('p', { class: 'assistant-note' }, 'AI guidance · Use the report to check the facts.'));
  panel.setAttribute('aria-labelledby', 'assistant-title');

  function syncModal() {
    const modal = app.classList.contains('assistant-open') && narrow.matches && !panel.hidden;
    scrim.hidden = !modal;
    panel.setAttribute('role', modal ? 'dialog' : 'complementary');
    if (modal) panel.setAttribute('aria-modal', 'true'); else panel.removeAttribute('aria-modal');
    for (const id of ['view', 'top', 'side']) document.getElementById(id).inert = modal;
  }
  function setOpen(open) {
    if (open) lastFocus = document.activeElement;
    app.classList.toggle('assistant-open', open);
    launcher.setAttribute('aria-expanded', String(open)); syncModal();
    if (open) input.focus(); else if (lastFocus?.isConnected) lastFocus.focus();
  }
  panel.addEventListener('keydown', e => {
    if (!narrow.matches || !app.classList.contains('assistant-open')) return;
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false); }
    if (e.key === 'Tab') {
      const controls = [...panel.querySelectorAll('button:not(:disabled), textarea, [tabindex="0"]')].filter(el => el.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  narrow.addEventListener('change', syncModal);
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(); } });
  async function ask(question) {
    const q = (typeof question === 'string' ? question : input.value).trim(), target = chat;
    if (!q || target.busy) return;
    target.draft = ''; input.value = '';
    await sendQuestion(target, q, { context: context() });
    if (target === chat && !panel.hidden && (!narrow.matches || app.classList.contains('assistant-open')) && !input.value) input.focus();
  }
  function paint() {
    const c = context(), screen = TAB_SCREENS[page + '.' + c.tab] || SCREENS[page] || SCREENS.start;
    screenLabel.textContent = [TABS[c.tab] || screen[0], { DE: 'Germany', IN: 'India' }[chat.country]].filter(Boolean).join(' · ');
    intro.replaceChildren(h('span', { class: 'assistant-intro-avatar', 'aria-hidden': 'true', html: AVATAR.guide }), h('h2', null, screen[1]), h('p', null, screen[2]));
    log.setAttribute('aria-busy', String(chat.busy));
    log.replaceChildren(...(!chat.messages.length ? [intro] : chat.messages.map(m => h('div', { class: 'assistant-msg ' + m.role },
      m.role === 'assistant' && avatar(), h('div', { class: 'msg-body' }, h('div', { class: 'msg-text' }, m.content), m.open && ACTION[m.open] && m.open !== page && h('button', { class: 'btn sm', onclick: () => { setOpen(false); openAssistantPage(m.open); } }, ACTION[m.open] + ' →'))))),
    ...(chat.busy ? [h('div', { class: 'assistant-msg assistant' }, avatar(), spinner('Thinking…'))] : []));
    const last = chat.messages.at(-1), questions = chat.messages.length ? last?.role === 'assistant' ? last.suggestions || [] : [] : screen[3];
    suggestions.replaceChildren(...(!chat.busy ? questions.map(q => h('button', { class: 'chip-btn', onclick: () => ask(q) }, q)) : []));
    error.hidden = !chat.error;
    error.replaceChildren(chat.error || '', chat.error && h('button', { class: 'btn sm', onclick: () => sendQuestion(chat, chat.retry, { context: context() }, true) }, 'Try again'));
    send.disabled = reset.disabled = chat.busy;
    log.scrollTop = log.scrollHeight;
  }
  addEventListener('agl:chat', paint);
  const observer = new MutationObserver(() => { const next = JSON.stringify(context()); if (next !== signature) { signature = next; paint(); } });
  observer.observe(view, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-assistant-tab', 'data-assistant-stage'] });
  return { launcher, update(name) {
    const next = conversation();
    if (chat !== next || page !== name) setOpen(false);
    if (chat !== next) { chat = next; input.value = chat.draft; }
    page = name; panel.hidden = !SCREENS[page]; launcher.hidden = panel.hidden;
    app.classList.toggle('has-assistant', !panel.hidden); syncModal(); paint();
  } };
}
