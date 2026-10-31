# Handoff, session 3 (home-page assistant, UI redesign, India map data)

For the next Claude Code agent. Read this first, then `HANDOFF.md` (sessions 1 and 2: payments, Masumi/Sokosumi, what was never verified). Where the two disagree, this file is newer. The user writes Russian; answer in Russian, keep code, commits and UI text in English.

Statements are tagged **[VERIFIED]** (observed this session) or **[NOT VERIFIED]**.

## 1. Where things are

| What | Value |
|---|---|
| Main checkout (what the user runs) | `/home/yehor/agrolend-`, branch **`Yehor`** |
| Worktree used this session | `/home/yehor/agrolend-/.claude/worktrees/main-chat-broken-c4e292`, branch `claude/main-chat-broken-c4e292` (same commit as `Yehor`) |
| Remote | `origin` = `git@github.com:qqxzew/agrolend-.git`, **public** repo |
| Local head | `a885872` ("Settings: optional config/assistant.env fallback…"). **One commit is not pushed**; `origin/Yehor` is at `5e132c0` [VERIFIED] |
| `main` | at `1740930`. `Yehor` is ~31 commits ahead. **No PR was opened**; the user never asked |
| Running app | `http://127.0.0.1:8080`, started in the background from the main checkout, log `state/dev-8080.log` [VERIFIED] |

Workflow the user prefers: edit and test in the worktree, ask, then fast-forward `Yehor` in the main checkout (`git merge --ff-only refs/heads/claude/main-chat-broken-c4e292`). Pushing is always a separate yes. Every merge/push was approved explicitly by the user each time; keep asking.

## 2. Run, restart, test

```bash
# start (background, from the main checkout; payment mode is dev-unpaid, so no real money)
cd /home/yehor/agrolend- && nohup /home/yehor/Desktop/Agro-land/.venv-dev/bin/python scripts/dev.py --unpaid --port 8080 > state/dev-8080.log 2>&1 &
```

Restart pitfalls (cost a lot of time) [VERIFIED]:
- `dev.py` starts 8 geo services (ports 8000-8003, 9000-9003) plus the gateway. Stopping `dev.py` can leave the children alive; a new start then fails with `address already in use` and `dev.py` exits ("a process exited"). Free **all** of `8080, 8000-8003, 9000-9003` first: `for p in $(ss -ltnp | grep -E ':(8080|800[0-3]|900[0-3])\b' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u); do kill $p; done`.
- Never `pkill -f "<text that also appears in your own command line>"`: it kills your own shell (exit 144). Use the bracket trick `pgrep -f "scripts/[d]ev.py"`.
- `kill -INT` did not stop `dev.py` (it was started in the background); plain `kill` works.
- Python caches the India parcel file (`@lru_cache` in `gateway/agroland/parcels.py`): restart after changing `data/in/parcels.geojson`. Static web files are served from disk with revalidation, so web edits need only a browser refresh.
- A sandbox/auto-mode classifier blocked some actions (killing the user's server before they said yes, copying the API key into a tracked file). Do not work around a denial; explain and let the user decide.

Tests (a venv with `requirements-dev.txt` is needed; the previous one lived in a session scratchpad and may be gone: `python3 -m venv .venv-dev2 && .venv-dev2/bin/pip install -r requirements-dev.txt`):
- `scripts/test_all.sh` runs everything. Last full run **[VERIFIED]**: gateway **70 passed** (`pytest gateway/tests`, ~80 s; it starts the real geo services), original geo suites all ok (10 files), Node agent **28/28** (`cd agent && npm test`). The Node run needs `npm ci` first. After the last small commit only `test_chat.py` + `test_hardening.py` were re-run (24 passed).
- Real-model smoke test of the assistant: see section 3.

## 3. Home-page assistant (OpenAI) [VERIFIED working]

- Endpoint `POST /api/chat` in `gateway/agroland/main.py`, logic in `gateway/agroland/chat.py`, tests `gateway/tests/test_chat.py`.
- It **only talks**: no orders, no payment, no workspace data. `open` is checked against an allow-list (`owner, farm, developer, orders, data, none`). The page turns it into an "Open … →" button. Input is trimmed (12 turns, 1000 chars), rate-limited per IP (`AGROLAND_RATE_CHAT_PER_HOUR`, default 60), upstream errors become a generic 503 (the key never leaks into a response).
- Model `gpt-4.1-mini` via `OPENAI_MODEL`; OpenAI-compatible base URL via `OPENAI_BASE_URL`. JSON-only reply: `{reply, open, suggestions[]}`.
- **Language**: the system prompt says "reply in the language of the visitor's latest message; bare greeting or ambiguous → English", and `language_hint()` appends a last system message derived from the script of the latest user message (Cyrillic → Russian/Ukrainian, non-ASCII → identify it). Tested by hand on ru/uk/de/es/pl/fr/en including slang ("ку") and mid-chat switches.
- The prompt contains a `GUIDE` block with the click path of every flow (button names exactly as in the UI). **When you rename a button or change a flow, update `GUIDE` in `chat.py`**, or the assistant will give wrong steps.
- If the key is missing or OpenAI fails, `web/js/views.js` `home()` falls back to keyword routing and shows "The assistant is not available right now…".
- **API key**: lives in `/home/yehor/agrolend-/.env` (`OPENAI_API_KEY=…`, mode 600, git-ignored; a copy exists in the worktree's `.env`, also ignored). `scripts/dev.py` loads `.env` into the process. `settings.py` also reads an optional `config/assistant.env` as a fallback (path overridable by `AGROLAND_ASSISTANT_ENV`; the test fixture points it nowhere). **That file does not exist.** The user asked to publish the key to GitHub; the repo is public, they were warned and confirmed, then decided to leave it local ("оставляй так"). **Do not commit the key unless they ask again, and tell them again that the repo is public.** The key was pasted into chat, so it is exposed in the transcript: suggest rotating it at platform.openai.com; after rotating, edit `.env` and restart.
- Docker: `deploy/docker-compose.yml` passes `OPENAI_API_KEY`, `OPENAI_MODEL`, `AGROLAND_RATE_CHAT_PER_HOUR` into the gateway. `scripts/preflight.py` prints a note if the key is empty. **[NOT VERIFIED]** in Docker (never started).

## 4. UI changes this session (all in `web/`)

- **Home** (`web/js/views.js` `home()`, CSS at the end of `web/css/app.css`): "AgroLand" wordmark, "What would you like to check?", composer with an agent select, three cartoon-avatar agent cards (inline SVG in `AVATAR`). The page never scrolls; in chat mode the message log scrolls by itself. "← Back" clears the conversation. Conversations are kept per workspace in `sessionStorage` (`agl.chat.<workspace id>`). Follow-up suggestion chips render under the last assistant message. No logo image above the chat, no search bar on this page, no "Pick on map".
- **Sidebar** (`web/js/main.js`): "New workspace" button, a "Workspaces" list like chats (click switches, × forgets on this device), nav = Ask the agent, role page, Orders, Data and sources. **The Map and Workspaces entries were removed on purpose.** `#/map` still exists as a route and the top-bar parcel search (shown on non-home pages) leads to it. `#/start` is now only the create-workspace form. `#/data` holds the agent table and coverage (moved off the home page).
- **Energy developer page** now mirrors the landowner flow: step 1 folds into a summary bar, step 2 audit folds after ordering, step 3 result full width, step 4 "Add to the pool", pool portfolio, "Demo tools" (demo neighbourhood) tucked into a `<details>`. The chosen site survives a refresh (`sessionStorage agl.dev.sel`). Matches & deals now refreshes itself every 5 s while a deal changes.
- Bugs fixed on the way: deal consent read a field the API does not send (`you.consent === 'accept'`); the demo counterpart was silently rejected for solar sites (now tries solar, the original tech, then wind); recorded savings vanished after reload; owner listings went stale and lost the tab; disclosed "Technology" was blank; a wind-speed warning was shown on solar audits (DE and IN `scoring.py`, now only wind/hybrid); India map opened at world zoom.
- Maps (`web/js/map.js`): legends, region buttons for India, zoom to the selected parcel, `ResizeObserver`, mouse wheel zooms only after a click on the map.
- Landing page (`web/index.html`) uses the new logo (`web/img/logo-mark.svg`, redrawn as SVG from the user's picture, so it may differ slightly from the original). The user deleted the "Germany and India" section from the landing page, so the header link `#coverage` there now goes nowhere: either remove the link or restore a target.

## 5. India data (`data/in/parcels.geojson`, generator `scripts/make_in_demo_parcels.py`)

82 fields: the original 5 rectangles (`IN-DEMO-1..5`, ids are referenced by docs and tests), 71 illustrative fields in Kutch (Gujarat) and Anantapur (Andhra Pradesh), and **6 real field outlines registered at 5am.earth on Cardano mainnet** (Nandur, Beed/Maharashtra, copied from `data/farm/in-mh/boundaries.geojson`, ids `IN-5AM-…`, `registered: true`). The illustrative fields are **not survey boundaries** and say so in `note`; survey numbers are invented. India has no open cadastre, and OpenStreetMap has almost no farmland polygons in these areas (checked via Overpass: 2 polygons), so no real polygon source exists. An India land audit ran successfully on a mosaic field and on a registered field [VERIFIED]. `gateway/tests/test_geo.py` guards the data.

## 6. Known gaps, ranked

1. **Payments were never tested for real.** Everything this session ran in `dev-unpaid` mode. No Masumi payment service, wallet, registration or Sokosumi task was run here; see `HANDOFF.md` §3/§11 for that status.
2. The Eve "Concierge" agent in `agent/` is the **Sokosumi-side** coworker and is **not running**; the home-page assistant is a different, simpler thing (`chat.py`). Do not confuse them. The earlier `agent/` tests pass (28/28).
3. The user's request "check that nothing is broken" was done through the API (both countries, all three services, listings, interest, outcomes, ICS, verify, document download) plus a browser pass on: home chat, sidebar, farm (India demo with crop section), landowner flow, developer pool deal end to end (consent, pay, NDA signed by both, disclosure + PDFs), India/Germany maps, landing page. **[NOT VERIFIED]**: German farm demo in the browser (API only), owner interest-accept buttons in the browser (API only), light/dark theme, and any phone layout other than the home page.
4. A browser console shows a `404` after switching workspace on a page that had an order panel polling the previous workspace's order. Harmless but unfixed.
5. `agent/.eve` was untracked per `HANDOFF.md`; not touched.
6. `main` is far behind `Yehor`; the user has not asked for a PR.

## 7. Style rules to keep

- Match the surrounding code (dense, one-line helpers in `web/js/*.js`; no frameworks). Files `gateway/agroland/chat.py` etc. are LF; some geo `scoring.py` files are **CRLF**: edit them byte-safe (Python text-mode rewrites flip every line ending and create a huge diff).
- Never print or commit the OpenAI key; never claim a payment, task id or on-chain fact that was not observed.
