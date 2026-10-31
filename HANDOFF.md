# HANDOFF — AgroLand (state as of 2026-10-31 ~00:15 local, machine 1)

Written for a Claude Code agent on a **different machine** that already has the needed logins (Sokosumi, Masumi/Cardano, model, Blockfrost). You have no access to the earlier conversation. Everything you need is this file + the repository + two files that a clone does **not** carry (section 4). Statements are tagged **[VERIFIED]** (observed on machine 1 on the stated date), **[LAST KNOWN]** (an external service state seen once; re-check), **[UNVERIFIED]** (assumption, report, or never executed).

---

## 0. Where to continue (read this first)

1. **State in one paragraph.** The AgroLand product is *implemented and tested locally* (30 gateway tests + 25 Node tests + original service suites, all green on 2026-10-30; browser-checked). **No real Cardano payment, no Masumi registration, no Sokosumi Task, no real model reply has ever been made.** `docs/EVIDENCE.md` is entirely PENDING and must stay that way until a real run produces evidence. Nothing in the repo is a proof of payment.
2. **Machine 1 left a half-configured Sokosumi setup:** Vendor `AgroLand` and Coworker `AgroLand Concierge` exist on preprod and were connected to the TUM-Hackathon workspace; access was **PENDING** (needs a TUM owner/admin approval). The Coworker runtime key is in **machine 1's** OS vault and does **not** transfer. See section 6 — **before creating anything on machine 2, run the read-only discovery commands and reuse what exists.**
3. **First 30 minutes on machine 2:** `git pull`; `scripts/test_all.sh` (offline, no accounts); read section 6 + 8; run the read-only Sokosumi checks in 6.4; decide **with the user** which Sokosumi account hosts AgroLand (section 6.3 — two accounts may now own overlapping resources).
4. **Then:** model-reply check and execution-only Task (no payment) → payment service + wallet + registration → one paid Task/job → evidence → deployment. Details and completion criteria in section 9.
5. **Do not:** start a second worker for the same Coworker; re-register agents (registry entries are immutable); enable `PAID_TASKS_ENABLED=true` or run `register` without the user's explicit go-ahead; put any key in a file that is tracked by git.

---

## 1. Goal and decisions (including every later user clarification)

**Goal.** Deliver one finished project for the **Cardano track of the TUM Blockchain & AI Hackathon (Munich, 30–31 Oct 2026)**, "Agentic Commerce on Cardano". Working prompt: `AgroLand_master_prompt.md` (untracked, section 4). Background/research: `kontekst-proekta-agent-proveryaet-zemlyu.md` (Russian, untracked).

**Product decisions (from the master prompt, still binding):**
* One unified product **AgroLand**; **three equally important, fully working workflows**: *landowner*, *tenant farm*, *energy developer*. Each is a real entry point; none is a placeholder; none requires another's workflow.
* **Germany and India** in all three workflows (units, currency, rules, documents differ per country).
* Improved **external frontend** with a public **landing page**, preserving the original concept (map + agent conversations + cards + understandable results); UI in **English**; internal docs may be Russian.
* **Real Masumi/Sokosumi integration** and **real payments on Cardano preprod**; qualification = at least one completed paid preprod job/request with its real transaction hash. Demo data is acceptable if labelled; calculations, services, transitions and payments must be real. Never fabricate Task IDs, registrations, transactions or receipts.
* **Deployment target: the team's existing server** (reproducible, persistent storage, readiness checks). Publishing/deploying/operating accounts are separate steps needing the user's authorization. Keys stay out of chat, logs, frontend code and Git.
* Use **Node.js 24, the quickstart's pinned dependencies and Sokosumi CLI 1.0.4** for the Masumi/Sokosumi integration (`https://github.com/masumi-network/tum-hackathon-quickstart`).
* First verify **a model reply and one execution-only Coworker Task**; add preprod payment setup **only after the user authorizes it**.

**Clarifications given by the user during the work (chronological):**
1. *"use docs to know about the possibilities if you can't reach the website due to login"* → when a site is login-only (Sokosumi UI), read the official docs / bundled CLI skills and say so in deliverables. (Done; documented in `README.md` §5.)
2. The user pasted their sudo password into chat. **It was not used** (policy: never authenticate with a password from chat). The user installed `libsecret-tools` themselves. *Recommend the user change that password.* Never repeat or store it.
3. *"Api key of blockfrost, credentials from cardano account login into masumi and sokosumi not possible right now (we have it on the other device) do what you can do without this"* → the Blockfrost key, Cardano wallet/Masumi login are on **the other device (machine 2)**. This is why none of the payment work was done on machine 1.
4. Answer **"Sokosumi + model"** (which external step first) → then **"TUM workspace"** (put the Coworker into the **TUM-Hackathon organization workspace**, not the Personal Workspace, because CLI 1.0.4's personal path was measured broken — section 6.5).
5. *"dont do masumi and sokossumi now - but only stuff for which you need some logins or approvals; just do the code side that you can"* → hardening work only; no external writes after that.
6. *"Commit it"* → commit `083d2d3`.
7. This handoff step: *do not modify product code, create registrations, make payments or deploy.* (Only `HANDOFF.md` was added; section 4 lists the one repo hygiene issue left for you.)

---

## 2. Actual architecture

```
Browser (web/)                      Sokosumi marketplace / Coworker Tasks
     │                                         │
     ▼                                         ▼
┌──────────────── Gateway (gateway/agroland, FastAPI, SQLite) ────────────────┐
│ workspaces (bearer token, no password) · parcels · listings · farm data     │
│ ORDER ENGINE (orders.py): quote → pay → run → deliver → hash → submit →     │
│    confirm → settle   (journal written BEFORE every external write)         │
│ /api/* website · /masumi/<service>/* MIP-003 · /internal/* Coworker worker  │
└───────┬───────────────────────────┬─────────────────────────┬──────────────┘
        │ loopback + shared keys    │                         │ seller side only
        ▼                           ▼                         ▼
 Geo services ×8 (services/geo)   state/ (SQLite, PDFs)   Masumi Payment Service (+Postgres) → Cardano preprod
 DE: audit·matcher·escrow·architect                         Blockfrost used to verify txs independently
 IN: audit·matcher·escrow·architect
```

**Key idea: ONE execution system.** The website, MIP-003 buyers and the Coworker all create the *same* order through `orders.Engine`; the report is produced once by the same runner. Channels only differ in packaging/hash: `web` → canonical JSON + MIP-004 hash; `mip003` → Markdown + MIP-004 hash (`hashing.result_hash_mip004`); `sokosumi` → Markdown + the quickstart's raw hash (`hashing.result_hash_raw`). Each report embeds `report_sha256` (canonical JSON), so results are comparable across channels.

**Money is handled only in the gateway.** Geo services run with payment bypass **on**, bind to loopback/private network, and are protected by shared keys. There is **no unpaid compute path** in `masumi` mode (the only unpaid mode is `AGROLAND_PAYMENT_MODE=dev-unpaid`, labelled UNPAID in API and UI, for developers).

### Where things live
| Path | What |
|---|---|
| `config/services.json` | **Single source of truth** for services, prices (tUSDM base units, 6 decimals), payment windows. Read by gateway, agent worker, registration script |
| `gateway/agroland/` | `settings.py`, `db.py`, `auth.py`, `hashing.py`, `masumi.py` (MPS client + Blockfrost verify), `orders.py` (engine), `services.py` (Land Audit, Lease Check runners), `farm.py`, `alkis.py`, `parcels.py`, `listings.py`, `pool.py` (Pool Access + runner), `geoclient.py`, `mip003.py`, `main.py` |
| `gateway/tests/` | pytest suite; `fake_audit.py` is a **testing stub** |
| `services/geo/` | internal DE+IN services folded in from the `geo-pooler` prototype (audit, matcher, escrow/NDA, architect). Its original docker-compose, Dockerfile and unpaid Sokosumi worker were **removed** (superseded) |
| `web/` | `index.html` (landing), `app/index.html` (app), `js/{core,views,order,map,main,landing}.js`, `css/`, vendored Leaflet |
| `agent/` | Eve Concierge (`agent/agent.ts`, `agent/instructions.md`, `agent/tools/*.ts`), `worker.mjs`, `planner.mjs`, `paid-order.mjs`, `gateway.mjs`, `register-agents.mjs`, quickstart files (`client.mjs`, `start.mjs`, `settlement.mjs`, `task-target.mjs`, `worker-lock.mjs`, `sokosumi-runtime.mjs`, `payment-registration.mjs`, …), `e2e/` |
| `data/` | `de/` ALKIS fragment (Magdeburg, 191 parcels) + A14; `in/parcels.geojson` (illustrative); `farm/{de,in}/` demo datasets |
| `deploy/` | `docker-compose.yml`, `Dockerfile`, `Caddyfile`, `systemd/agroland-{eve,worker}.service` |
| `scripts/` | `dev.py`, `stack.py`, `test_all.sh`, `preflight.py`, `seed_demo.py`, `walk_deal.py`, `evidence.py`, `make_in_demo_parcels.py` |
| `docs/` | `DEPLOY.md` (team checklist + ordered steps), `VERIFICATION.md`, `EVIDENCE.md` (all PENDING), `DEVFOLIO.md`, `VIDEO_SCRIPT.md`, `ru/ЗАПУСК.md` |

### Agents and paid services (README.md has the full catalog)
| # | Name | Paid Masumi service | Price (tUSDM) | From website | From Sokosumi |
|---|---|---|---|---|---|
| 1 | **Land Audit** | yes, `land_audit` | 1.00 | owner/developer | MIP-003 `/masumi/land_audit`; Coworker Task |
| 2 | **Lease Check** | yes, `lease_check` | 2.00 | farm | MIP-003 `/masumi/lease_check`; Coworker Task |
| 3 | **Pool Access** | yes, `pool_access` (per party; pay window 48 h, deliver 7 d) | 3.00 | developer only | **not hireable as anonymous job** (needs both parties' consent+signatures); its `start_job` returns 400 by design |
| 4 | **AgroLand Concierge** | no separate registry entry | — | — | Sokosumi **Coworker** (language model, Eve): turns a free-text Task into one validated, priced order, or asks/declines; posts a labelled AI summary after delivery |

Roles: **our website** = the complete external product UI; **Sokosumi** = discovery/hiring (marketplace MIP-003 agents) and the Coworker Task UI; **Masumi/Cardano** = escrowed payment, result-hash on-chain, registry; **Concierge** = the LLM agent with real tools (`coverage`, `validate_order`, `get_report`); all calculations are deterministic.

### Original implementations: kept / merged / replaced (and why)
* **Farm check:** the original JS (`case3-farm`) and the Python port inside AgroLand give identical results on the German data (5 findings, €1,440 identified, €720 negotiable) [VERIFIED]. **Kept the Python**, rewritten generically in `gateway/agroland/farm.py` (units/currency from dataset settings; no agent fee; "achieved savings" recorded only by the user). Reason: same stack as the gateway, one maintained engine.
* **Owner MVP (AgroLand.tar):** corridor screening `alkis.py` retained; the single-operator SQLite listing flow with a "demo payment" flag was **replaced** by per-workspace listings + real order payment + allow-listed marketplace + per-developer boundary disclosure. Reason: the original had no auth and simulated payment.
* **geo-pooler:** audit/matcher/escrow/architect (DE+IN) retained as **internal services**; their own Masumi payment code is unused (bypass on); the **unpaid Sokosumi worker was replaced** by `agent/worker.mjs`; docker-compose replaced by `deploy/` + `scripts/stack.py`.
* **Frontend:** original `frontend/` replaced by `web/` (landing + app). The map-plus-cards concept is kept (Leaflet map, cards, order timeline); the chat is replaced by guided forms and an order panel (a scripted "chat" would have simulated an agent).
* **Quickstart:** its `paid-task.mjs` (payment embedded in the worker) was **replaced** by `agent/paid-order.mjs`, which delegates the seller side to the gateway and only posts the Core `masumiPayment` event / completion. Reason: one payment path for all channels.

---

## 3. Implementation status

### Complete and verified locally (2026-10-30/31, machine 1)
* Order engine incl. idempotency (same key/refresh → same order, no 2nd payment request), journalled payment stages, frozen-on-uncertain writes, deadline handling, restart-resume — **against a mock payment service** (`FakeMps`).
* Masumi seller client, MIP-003 router (`start_job`/`status`/`input_schema`/`availability`/`demo`) — mock payment service.
* Workflows (both countries) — see matrix below.
* Access control per workspace, owner-only documents, allow-listed marketplace, controlled boundary disclosure, rate/size limits, CSP — tests.
* Web: landing and app render; CSP does not break them (in-browser).
* Node: planner validation, paid-order state machine (fake gateway/Core), quickstart tests; Eve boots with the 3 tools; scripted-model e2e.

### Implemented but NOT verified against external services
* Any real **Masumi payment service** call (`create_payment`, `resolve`, `submit_result`, `purchase`), real funds-locked/result-hash/settlement transactions, `verify_tx_on_blockfrost` against live Blockfrost.
* `agent/register-agents.mjs`: the **Fixed pricing field names are UNVERIFIED** against a live payment service OpenAPI (marked in code).
* `/api/orders/{id}/pay-demo-wallet` (buyer wallet purchase): payload mirrors the quickstart; never run.
* Sokosumi: Task creation → `runtime start` → plan → quote/complete, the Core `masumiPayment` event, `runtime receipt`, comment replies — **never executed** (no model key, workspace access PENDING).
* Real **model reply** (Eve + a real provider). Only a scripted stub model was used.
* `deploy/docker-compose.yml`, Caddy, systemd units: **never started** (no Docker on machine 1; compose parses as YAML only). Payment-service image `masumi-payment-service:0.29.0` migration/seed step is described in `docs/DEPLOY.md` but not exercised.
* MIP-003 listing appearing in Sokosumi after registration (docs say preprod listings with tUSDM pricing appear automatically when online) — [UNVERIFIED].

### Workflow readiness (do not read "implemented" as "works end-to-end with payments")
| Workflow | DE | IN | Local verification | Missing for real use |
|---|---|---|---|---|
| **Owner** (parcel → Land Audit → document → listing → consent → interest → disclosure) | map of 191 real ALKIS parcels, A14 corridor signal, live audit | illustrative demo parcels + live audit (OSM) | API tests for both countries; live audits DE (GO 95) / IN (CONDITIONAL_GO 80); browser: map select + order panel | real payment; **UI path for listing form/interest accept not clicked through in a browser**; Sokosumi side only via Land Audit |
| **Farm** (leases vs record vs fields; identified / negotiable / achieved; reminders) | EUR, ha, ALKIS record, demo farm | INR, acre, 7/12 record, demo farm | tests + parity with JS; browser: DE end-to-end incl. reload | real payment; IN farm **not opened in a browser**; CSV upload tested via API only; `prompt()`-based "record saving" UI is basic |
| **Developer** (audit → pool → teaser → consent → pay → NDA → disclosure + plan + PDFs) | live deal run with real matcher/escrow/architect | same, IN | `test_pool.py` (real services, stub audit) DE+IN; **live** deals via `scripts/walk_deal.py` DE+IN (unpaid mode) | real payment of both parties; **consent/pay/sign buttons not clicked through in a browser** (only viewed the finished deal); real results were *not viable* (see below) |

**Honest findings in real runs:** live DE and IN pool deals both computed "joint project not viable / pooling not beneficial" (DE NPV −€1.82 M, no substation within 10 km in OSM data; IN NPV −₹31.4 M); split falls back to area key 50/50 with warnings. This is the model working, not a bug; the landing page says so.

### Still to write / known gaps
* **Repo hygiene (do first):** commit `083d2d3` accidentally tracks **244 Eve runtime files under `agent/.eve/`** (2.3 MB: workflow-data, traces, dev-runtime snapshots). Scan found **no keys** (only the fake model name `zai/fake`), but they should be untracked: `git rm -r --cached agent/.eve` and add `agent/.eve/` to `.gitignore`. It was **not fixed** (handoff-only step). `origin/main` already points at `083d2d3` locally (see §4) so the files may be on the remote.
* x402 pay-per-request path — **not implemented** (optional; the Masumi path is the integration).
* CIP-30 browser-wallet payment on the website — not implemented (pay via Masumi/Sokosumi wallet using the payment identifier, or operator-funded demo wallet).
* Strong authentication (workspaces are bearer tokens in browser storage).
* Ownership/title verification, Bavarian ALKIS, qualified e-signatures, Indian record lookups — out of scope, stated in README.
* No automated browser/UI tests (only manual in-app browser checks).
* `docs/DEVFOLIO.md`, `docs/VIDEO_SCRIPT.md` are drafts with PENDING evidence/links.
* The `npx skills add … masumi` install command was never run (guides read directly).

### Remaining simulations / demo data / limitations
* All farms/owners/contracts are fictional (labelled). Magdeburg parcels are real ALKIS geometry (no owner data). India parcels are **illustrative rectangles** (survey numbers invented). Benchmarks (€400/ha, ₹50,000/acre) are labelled demo values.
* Two-party flows use two workspaces; `POST /api/demo/counterpart` creates a labelled demo counterparty that **still must consent and sign itself** (no action on its behalf).
* Wind speed is a 30-day (DE) / 2022–2024 ERA5 mean (IN) screening value; India protected-area/habitation screens are OSM-based with unmeasured completeness; contracts/NDAs are machine-generated drafts for lawyer review.
* Live audits take ~40 s (DE) to ~110 s (IN); public Overpass can be slow.

---

## 4. Git and files

**[VERIFIED 2026-10-31 ~00:15]**
* Branch `main`; HEAD `083d2d33764eb0dae1ace802731a23e4b30c76a4` ("AgroLand: shared order engine, three workflows (DE + IN), Masumi/Sokosumi integration code"), the only commit.
* Remote `origin` = `git@github.com:9Sk1p/Agro-land.git`. The local tracking ref `origin/main` is at `083d2d3` and `git status -sb` shows `main...origin/main` (not ahead). **This agent never pushed;** the user (or the desktop app) must have. The tracking ref may be stale — run `git fetch` and compare. Whether the GitHub repo is public: [UNVERIFIED].
* **Tracked changes uncommitted: none** other than this `HANDOFF.md` (untracked until committed).
* Untracked, important, **not in a normal clone**: `AgroLand_master_prompt.md`, `kontekst-proekta-agent-proveryaet-zemlyu.md`. **Copy these two files to machine 2 manually** (the user left them untracked on purpose; the Russian note holds team strategy — keep out of a public repo unless the user decides otherwise).
* Ignored but present on machine 1 (not transferred, mostly regenerable): `.venv-dev/`, `.pytest_cache/`, `agent/node_modules/`, `agent/.env` (private), `agent/.local/` (ids, e2e journals — no Task journals), `agent/.eve/` (runtime junk, see above), `state/` (dev databases/logs/tokens), raw inputs `AgroLand.tar`, `case.tar.gz`, `geo-pooler.tar`, `_src_agro/`, `_src_case/`.
* ⚠ `geo-pooler.tar` contains a **live `.env` with a wallet seed phrase and API keys** (the prototype's). It was **never copied into the repo**. An *extracted copy* also exists in the previous session's scratchpad on machine 1 (`/tmp/claude-1000/-home-yehor-Desktop-Agro-land/1e0aadc9-5c05-4260-ad21-947b8920161e/scratchpad/src/geo/geo-pooler/.env`). **Do not transfer the tarball to machine 2; ask the user to delete the extracted copy.** If that wallet was more than a throwaway test wallet, treat it as compromised. You do not need it: the registered agent identifiers can be read from the existing payment service/registry on machine 2.
* A `memory` folder of the previous Claude session exists only on machine 1 (`~/.claude/projects/-home-yehor-Desktop-Agro-land/memory/`); its content is superseded by this file.

---

## 5. Verification (what exactly was run)

**All commands from the repo root. Python 3.14.4 (venv `.venv-dev`), Node 24.22.2.**

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # machine 1 used .venv-dev
scripts/test_all.sh                       # web syntax + gateway + original geo suites + node; "ALL OFFLINE TESTS PASSED"
.venv/bin/python -m pytest gateway/tests -q          # 30 tests
(cd agent && npm ci && npm test)                      # 25 tests
(cd agent && AGROLAND_URL=http://127.0.0.1:8080 AGROLAND_INTERNAL_KEY=<dev key> npm run e2e:fake)   # needs the stack running
python scripts/dev.py --unpaid            # local stack, DEV ONLY (UNPAID banner)
python scripts/seed_demo.py --pool        # demo workspaces; real audits (minutes)
python scripts/walk_deal.py --country DE|IN
python scripts/preflight.py --url http://127.0.0.1:8080
python scripts/evidence.py                # prints PENDING when no on-chain payment exists
```

**Results [VERIFIED, 2026-10-30 ~23:52 local, last full run, then only docs/config/commit changed]:** `test_all.sh` → all passed: gateway **30**, Node **25** (planner, paid-order, quickstart tests), original `services/geo/tests/test_*.py` all `ok`. `npm run e2e:fake` passed earlier the same evening. JS original farm suite (`case3-farm`, `node --test`) 14/14 (on the raw copy, not in the repo).

**Used stubs/mocks (NOT evidence of real services):** `FakeMps` (mock Masumi payment service) in `gateway/tests/test_orders.py`/`test_mip003.py`/`test_hardening.py`; `gateway/tests/fake_audit.py` (stub audit for pool tests; matcher/escrow/architect are **real** subprocesses); fake gateway + fake Sokosumi Core in `agent/paid-order.test.mjs`; `agent/e2e/fake-openai.mjs` (scripted model; Eve runtime, tools and gateway are real).

**Contacted live external services:** live DE/IN audits through the gateway (BKG VG250, OSM Overpass, BfN/EEA, PVGIS, Open-Meteo, Nominatim, Copernicus DEM): DE ALKIS parcel solar → **GO 95**, green signal, 38 s; IN Gujarat demo site wind → **CONDITIONAL_GO 80**, 111 s; the old prototype's `test_worker.py` live: GO 88 / CONDITIONAL_GO 84 / NO_GO 10 (national park). Live pool deals DE+IN via the real matcher with real audits (unpaid mode). Sokosumi preprod **read-only** calls. Doc fetches (masumi.network, developers.cardano.org, hackathon.tum-blockchain.com).

**Browser (in-app browser, 2026-10-30):** landing page (prices load from `/api/config`); workspace creation; Lease Check DE end-to-end (price → start → result persists after reload); owner map with 191 parcels and selection; developer deals view of a finished deal; 375 px layout of two views; CSP check (landing + app + map tiles). Bugs found/fixed: stray `null` text, result card not updating, table overflow, oversized-CSV 500. **Not browser-tested:** IN farm, owner listing form and interest accept, developer consent/pay/sign buttons, light theme, `/orders` page, drawing an outline.

**Unfinished tests:** everything in "not verified" (§3); no CI configured; no UI automation.

**Real evidence status [VERIFIED]:** **no** real Task IDs, **no** payment transaction hashes, **no** seller-receipt evidence exist. The gateway DB on machine 1 has 7 orders, all `dev-unpaid` + `delivered`, **0** with any chain transaction (`select … funds_locked_tx` count = 0). `agent/.local/` has no Task journals and no `evidence/`. `docs/EVIDENCE.md` correctly says PENDING.

---

## 6. Masumi, Sokosumi, the model

### 6.1 Resources created on machine 1 (public IDs, not secrets) — **reuse, do not duplicate**
| Thing | Value | Source / date |
|---|---|---|
| Sokosumi target | preprod (`https://api.preprod.sokosumi.com`) | [VERIFIED] |
| Account used on machine 1 | user id `01a18c25-2293-77e6-8493-afa58d319110`, `platformRole: user`; member of TUM-Hackathon only. **Whether it is the team's intended account is [UNVERIFIED]** (the user was asked and answered "TUM workspace" about something else) | `sokosumi --preprod auth whoami --json` |
| Vendor | `AgroLand`, slug `agroland`, id `01a18eff-17c7-766b-a3ec-b5d0aaa90364`, role admin | created 2026-10-30 22:47 UTC; re-read [VERIFIED] 2026-10-31 |
| Coworker | `AgroLand Concierge`, slug `agroland-concierge`, id `01a18eff-2268-705c-acb4-c0d803804044`, capability `tasks` | created 2026-10-30 22:47 UTC; re-read [VERIFIED] |
| Workspace | TUM-Hackathon, organization id `01a17942-e6dd-724f-bae6-458b6a0f715a`, slug `tum-hackathon-u4ve65`, workspace id `01a17942-e6fa-73ee-8d10-c1b835a335fd` | `workspaces list` |
| Coworker→workspace access | id `01a18eff-2e50-772a-b508-80cfdad939b7`, status **PENDING** | **[LAST KNOWN]** 2026-10-30 22:47 UTC; not re-checked (re-checking = repeating `coworkers connect`, a write) |
| `taskSeatEligible` | `true` | [VERIFIED] 2026-10-31 |
| Tasks for this Coworker in TUM workspace | none (`tasks list` empty) | [VERIFIED] 2026-10-31 |
| Masumi registry entries for AgroLand's 3 agents | **none** (no `docs/registration-state.json`; `register-agents.mjs register` never run) | [VERIFIED] |
| Payment service / wallets / Blockfrost | **not configured on machine 1** | [VERIFIED] |
| Payment mode | gateway default `masumi` (needs payment env); machine 1 ran `dev-unpaid` locally. Worker `PAID_TASKS_ENABLED=false` | [VERIFIED] |

### 6.2 Resources from the earlier prototype (probably on machine 2's account) — [UNVERIFIED], from the prototype's `sokosumi/README.md` (now removed from the repo)
Vendor `Geo Pooler` (slug `geo-pooler-land`, id `01a18e90-74bd-7768-a74b-ee85b39638bc`), Coworker `Land Audit Germany` (id `01a18e91-38fc-7119-9e4e-adfd7c1dd666`; Personal workspace GRANTED, TUM-Hackathon "needs owner/admin approval"), prototype URL `https://audit.mrrobot.hackclub.app` (possibly the "existing server": Hack Club Nest, whose SSH gateway forbids port forwarding). The master prompt says the German auditor and NDA configurations already carried Masumi agent identifiers with payment bypass off; **those values lived in the prototype's `.env` (not copied)** — read them from the existing payment service/registry on machine 2 instead. None of this proves a registration is current or a payment succeeded. **One self-service Vendor per account** is a platform limit.

### 6.3 Account decision needed (do this before creating anything)
Machine 2's logged-in account may be the *prototype's* account (owns `Geo Pooler`) while machine 1 created `AgroLand` under a *different* account. Run section 6.4, then **ask the user** which account should own AgroLand. Options: (a) use machine 2's account: it may need its own Vendor/Coworker (if it already has an administered Vendor, `vendors create` will be refused — reuse that Vendor and provision a Coworker under it, or reuse an existing Coworker via `coworkers update`/rename — ask); (b) log machine 2 into the machine-1 account and reuse `AgroLand`/`AgroLand Concierge`. Either way, **retire the unused resources only with the user's say-so** (none of the CLI commands for deleting are documented here).

### 6.4 Read-only discovery on machine 2 (safe; run first)
```bash
sokosumi --version                                  # must be 1.0.4 (pinned by the TUM guide)
sokosumi --preprod auth status --json && sokosumi --preprod auth whoami --json
sokosumi --preprod workspaces list --json
sokosumi --preprod vendors me --json
sokosumi --preprod coworkers list --scope owned --json
sokosumi --preprod workspaces check 01a17942-e6dd-724f-bae6-458b6a0f715a --json
sokosumi --preprod tasks list --organization-slug tum-hackathon-u4ve65 --json
```
If `01a18eff-2268-705c-acb4-c0d803804044` is **not** listed under `coworkers list --scope owned`, machine 2 is a different account (see 6.3). If it is listed, check access: the CLI has no read-only access query; repeating `coworkers connect COWORKER_ID --vendor-id VENDOR_ID --workspace-id ORG_ID --json` only re-requests (never `register`). `GRANTED` is required before any Task.

### 6.5 CLI 1.0.4 vs the personal workspace — measured, may have changed
[VERIFIED 2026-10-30 22:45 UTC] `workspaces list --personal` → HTTP 404 `route_not_found` on `/v1/users/me/workspace-access` (the route the prototype's notes said had disappeared; they recommended CLI 1.1.0). `tasks list --organization-slug <TUM>` works. `coworkers register/connect --personal` use the same endpoint and were **not called** (so their failure is inferred, not observed). Hence the Coworker was put into the TUM organization workspace. Re-test; if the personal path works for you, it is the quickstart's preferred first test. Do not change CLI version without the user's word.

### 6.6 Credentials: what exists where (no values here)
| Credential | Belongs to | Stored | Transfers? |
|---|---|---|---|
| Sokosumi **OAuth login** (human) | the CLI user session | OS credential vault via `secret-tool` (needs `libsecret-tools` + GNOME Keyring); token expiry seen `2026-10-31T00:42Z` | **No** — log in on machine 2: `sokosumi --preprod auth login` |
| Coworker **runtime key** | the Coworker (worker authentication only; never used for human login, never in `.env`) | OS vault via `sokosumi runtime key-import` (machine 1 holds one for `01a18eff-2268…`) | **No** — create/import on machine 2: `sokosumi --preprod coworkers api-key COWORKER_ID --json \| sokosumi --preprod runtime key-import --coworker-id COWORKER_ID --api-key-stdin --json`. [UNVERIFIED] whether `api-key` rotates/invalidates the machine-1 key; machine 1 has no running worker, so it does not matter. Requires Vendor admin of the owning account |
| Model API key | `agent/.env` `ZAI_*` | `agent/.env` (chmod 600, git-ignored) | create on machine 2 |
| Masumi **admin key** | payment service | `agent/.local/mps.env` (`ADMIN_KEY`) | machine 2 |
| Masumi **runtime ReadAndPay token** (wallet-scoped) | gateway seller calls | `agent/.local/mps-runtime.env` → copy into root `.env` as `MPS_RUNTIME_TOKEN` | machine 2 |
| Selling wallet mnemonic | payment service | root `.env` `SELLING_WALLET_PREPROD_MNEMONIC` (compose only), dedicated test wallet | machine 2; never reuse another project's wallet |
| Blockfrost project id | gateway verification + payment service | root `.env` and agent env `BLOCKFROST_API_KEY_PREPROD` | machine 2 |
| Internal keys (`AGROLAND_INTERNAL_KEY`, `GEO_*_KEY`) | gateway ↔ worker ↔ geo services | root `.env`; `AGROLAND_INTERNAL_KEY` also in `agent/.env`; local dev ones auto-generated in `state/dev-keys.env` | generate fresh: `openssl rand -hex 24` |

### 6.7 Configuration variables (purpose)
Root `.env.example` (copy to `.env`): `AGROLAND_PAYMENT_MODE` (`masumi` real | `dev-unpaid` dev only), `AGROLAND_PUBLIC_URL`, `AGROLAND_STATE_DIR`, `AGROLAND_INTERNAL_KEY`, `AGROLAND_TRUST_PROXY` (true only behind Caddy), `AGROLAND_RATE_SESSIONS_PER_HOUR`, `AGROLAND_RATE_ORDERS_PER_HOUR`, `GEO_{DE,IN}_{INTERNAL,ESCROW,ARCHITECT}_KEY`, `MPS_URL`, `MPS_RUNTIME_TOKEN`, `SELLER_VKEY`, `PAYMENT_SOURCE_INDEX`, `AGENT_IDENTIFIER_{LAND_AUDIT,LEASE_CHECK,POOL_ACCESS}` (printed by `register:status`), `BLOCKFROST_API_KEY_PREPROD`, optional `BUYER_MPS_URL`/`BUYER_MPS_TOKEN` (separate funded buyer wallet for the website "demo wallet" button), compose-only `POSTGRES_PASSWORD`/`ENCRYPTION_KEY`/`ADMIN_KEY`/`SELLING_WALLET_PREPROD_MNEMONIC`/`COLLECTION_WALLET_PREPROD_ADDRESS`, `AGROLAND_DOMAIN` (Caddy). `agent/.env.example`: `ZAI_API_KEY`, `ZAI_BASE_URL`, `ZAI_MODEL`, **`ZAI_CONTEXT_WINDOW_TOKENS` (required for a custom model; Eve refuses to start without it)**, `EVE_PORT`/`EVE_URL` (must match, 127.0.0.1), `COWORKER_ID`, `SOKOSUMI_ORGANIZATION_ID`+`SOKOSUMI_ORGANIZATION_SLUG` (**both or neither**; both = TUM workspace, neither = personal), `PAID_TASKS_ENABLED`, `AGROLAND_URL`, `AGROLAND_INTERNAL_KEY`, `MPS_URL`, `AGENT_AUTHOR` (required for registration), `PUBLIC_BASE_URL` (https public URL for `apiBaseUrl`), `BLOCKFROST_API_KEY_PREPROD`.

**State of machine 1's `agent/.env` [VERIFIED, presence only]:** `COWORKER_ID`, `SOKOSUMI_ORGANIZATION_ID`, `SOKOSUMI_ORGANIZATION_SLUG` set to the §6.1 values; `PAID_TASKS_ENABLED=false`; `AGROLAND_URL` set; **empty:** all `ZAI_*`, `AGROLAND_INTERNAL_KEY`, `AGENT_AUTHOR`, `PUBLIC_BASE_URL`, `BLOCKFROST_API_KEY_PREPROD`. That file does not transfer.

### 6.8 Open question: payment token
`config/services.json` prices in **tUSDM** (preprod unit `16a55b2a…745553444d`, 6 decimals) because the quickstart and the Sokosumi listing guide require USDM settlement. The Masumi "Top Up Your Wallets" guide says USDM is **not available on preprod** and only test ADA is needed. Unresolved: ask the Masumi engineer which holds for the Sokosumi Core buyer. The token is defined in one place (`payment.token`). Also unresolved: whether registry pricing should be `Fixed` (used for marketplace display) or `Dynamic` (the quickstart's choice).

---

## 7. Environment and running processes (machine 1)

* OS Linux 7.0.0-38-generic; Python 3.14.4 (Dockerfile uses 3.12); Node v24.22.2, npm 12.2.1; Sokosumi CLI 1.0.4; `secret-tool` installed (`/usr/bin/secret-tool`); GNOME Keyring running; **Docker not installed**.
* Python deps pinned in `requirements.txt`/`requirements-dev.txt`; Node deps pinned in `agent/package-lock.json` (`npm ci`; `npm audit` reports 3 known findings in eve/undici/zod — left pinned as required).
* Ports (all 127.0.0.1): gateway **8080**; DE audit/matcher/escrow/architect **8000–8003**; IN **9000–9003**; Eve (when started) 21949 by default (e2e used 21960/21961); payment service (planned) 38127 (quickstart) / 3001 (compose admin).
* **Currently running [VERIFIED 2026-10-31 ~00:15]:** `scripts/dev.py --unpaid --port 8080` (PID 32671, started 2026-10-30 23:57) with all 8 geo services and the gateway, in **dev-unpaid** mode. **No worker, no Eve agent, no payment service is running.** These were left running by accident; stop before transfer if you want a clean state (use bracketed patterns — plain `pkill -f` patterns can match and kill the invoking shell, exit 144):
  ```bash
  pgrep -f "[s]cripts/dev.py" | xargs -r kill; sleep 2; pgrep -f "[u]vicorn (app|matcher|escrow|architect|india|agroland)" | xargs -r kill
  ```
* Data locations: gateway SQLite `state/gateway/agroland.sqlite3` (users 14, orders 7, parcels 8, listings 0, pool_parcels 4, pool_deals 4, documents 0, farm_datasets 0), uploaded documents `state/gateway/documents/`, pool PDFs `state/gateway/pool/<order id>/`, geo service DBs `state/{de,in}_{jobs,matcher,escrow,architect}.sqlite3`, logs `state/logs/`, local tokens `state/demo-tokens.json` and `state/dev-keys.env` (mode 600, **local demo only**). Task journals: `agent/.local/<TASK_ID>.json` — **none exist**. Worker lock: `agent/.local/worker.lock` — **absent**. Evidence: `agent/.local/evidence/` and `docs/evidence/` — **absent**.
* **Unfinished orders/payments/tasks needing preservation: none.** All 7 orders are `delivered` + `dev-unpaid` + no chain tx (demo data, safe to discard; reproducible with `scripts/seed_demo.py`). No payment requests, purchases, registrations or Tasks are in flight anywhere.

### Safe execution transfer (no double workers, no duplicate charges)
1. Machine 1 has never run a worker; nothing to hand over. Still: confirm no `worker.mjs` runs on machine 1 (`pgrep -af "[w]orker.mjs"` → empty). **One worker per Coworker and workspace**; the lock is machine-local, so *you* enforce it across machines.
2. Before first run on machine 2 check `agent/.local/` for journals; a journal with phase `starting` or a paid stage ending in `-pending` means an uncertain external write: **inspect Task events / gateway order, never replay**. (Quickstart rule.)
3. Duplicate charges: orders are idempotent by `external_ref` = Sokosumi Task id (Coworker) / `identifier_from_purchaser` (MIP-003) / idempotency key (web); `Engine.pay` is a no-op after the first payment request; uncertain payment/submit writes freeze the order (`*-uncertain`). Do not delete order rows to "retry".
4. Do not point two gateways at the same payment service/agent identifiers with different databases.

---

## 8. Transfer to machine 2

**Through Git:** everything tracked (431 files at `083d2d3`, including docs, deploy files, scripts, the two example env files). Run `git fetch && git log --oneline -3` to confirm you have `083d2d3` or later.

**Separately (manual, private):** `HANDOFF.md` if not committed; `AgroLand_master_prompt.md`; `kontekst-proekta-agent-proveryaet-zemlyu.md`; and *secrets created on machine 2 itself* (never copy from machine 1): `agent/.env`, root `.env`, `agent/.local/mps.env`, `agent/.local/mps-runtime.env`, the vault entries.

**Do not transfer:** `geo-pooler.tar` / any extracted `.env` from it; `state/` (incl. `demo-tokens.json`, `dev-keys.env`); `.venv-dev/`; `agent/node_modules/`; logs.

**Check first on machine 2:** `git status`, `node -v` = 24.x, `python3 --version` ≥ 3.12, `sokosumi --version` = 1.0.4, `secret-tool --version`, Docker presence (`docker compose version`), free ports 8000–8003/9000–9003/8080, `npm ci` works, `scripts/test_all.sh` passes, then section 6.4.

**Path/environment-dependent configuration:** `scripts/dev.py` and `scripts/stack.py` use paths relative to the repo; `AGROLAND_STATE_DIR` defaults to `<repo>/state`; compose uses `/data/gateway` volumes; systemd units assume `/opt/agroland` and user `agroland` (edit them); `config/services.json` is read relative to the repo by the gateway and via `new URL('../config/services.json', import.meta.url)` by the agent (**keep `agent/` and `config/` siblings**); the worker runs the `sokosumi` binary from `PATH` (not a Windows-style path). Local-run keys are generated into `state/dev-keys.env` (ignored).

**Public package hygiene:** the repo contains no secrets (scanned before commit; `.env`, `state/`, `.local/`, tarballs are git-ignored). `HANDOFF.md` contains public Sokosumi IDs and an account hint — decide before making the repository public. `docs/ru/` and the two untracked notes are internal.

---

## 9. Next actions

### A. For the next agent (in order)
1. **Verify the received project:** `git fetch`, HEAD, `scripts/test_all.sh`. Fix repo hygiene: `git rm -r --cached agent/.eve` + `.gitignore` entry + commit (ask the user before pushing).
2. **Verify access (read-only):** section 6.4. Resolve 6.3 *with the user*. Do not create Vendor/Coworker/registry entries before that.
3. **Model + execution-only checks** (no payment): fill `agent/.env` (user supplies key values privately), `cd agent && npm ci`, `npm start` (terminal 1), `npm run worker` (terminal 2, wait for `Continuous worker running`). Create Task(s) with `--organization-slug tum-hackathon-u4ve65` (or `--personal` if the personal path works): (a) "What can AgroLand do and what does each cost?" (model reply from `coverage`); (b) "Audit a solar site at 52.0746, 12.7329 in Germany" → with `PAID_TASKS_ENABLED=false` it must complete with a **quote** (nothing run/charged). Confirm `COMPLETED`, then a follow-up comment reply. Needs the gateway running (`python scripts/dev.py` in masumi mode or the compose stack) and `AGROLAND_INTERNAL_KEY` in `agent/.env`. Record Task IDs and replies **only as observed**.
4. **Resolve the token question (6.8)** with the Masumi engineer; verify `register-agents.mjs` Fixed-pricing field names against the payment service OpenAPI; fix code if needed (`docs/DEPLOY.md` B3).
5. **Payment setup** (user authorization required): payment service + dedicated seller wallet + test funds, `agent/docs/payment-state.json`, `npm run mps:key`, copy token to root `.env`.
6. **Register the 3 agents** (user authorization; immutable; spends test ADA): `register-agents.mjs plan` → review → `npm run register` → `npm run register:status` until registered → put `AGENT_IDENTIFIER_*` and `SELLER_VKEY` into root `.env` → `scripts/preflight.py`. **Check the existing registry first** (the prototype may already own agents; avoid duplicates).
7. **One real paid job** (user authorization): set `PAID_TASKS_ENABLED=true`, restart the worker, run a Task; expect order → payment requested → funds locked → report delivered → Task COMPLETED → result hash confirmed → settlement. Verify seller **net receipt** (Core receipt + Blockfrost; `agent/.local/evidence/<TASK_ID>.json`); `python scripts/evidence.py --write docs/evidence/orders.json`; fill `docs/EVIDENCE.md`, `docs/DEVFOLIO.md`, `docs/VIDEO_SCRIPT.md` with real values. Also exercise the MIP-003 path (hire Agent 1/2 as a Sokosumi marketplace Job) and the website payment path.
8. **Browser-test the untested UI paths** (§5 "Not browser-tested"), then deployment per `docs/DEPLOY.md` (compose first start, Caddy TLS, systemd for worker/Eve, `scripts/preflight.py`).
9. Update `README.md`, `docs/VERIFICATION.md` with what was *really* verified; keep PENDING markers until then.

### B. For the user
Confirm the Sokosumi account that should own AgroLand (6.3); supply model key values and Blockfrost key privately on machine 2; confirm/ask for the TUM-Hackathon admin approval of the Coworker access (PENDING as last known); decide the token question with Masumi; authorize payment setup, registration, the first paid job, and deployment separately; provide the server/domain; delete the extracted `geo-pooler/.env` copy and rotate the pasted sudo password; decide whether the repo goes public and whether the Russian notes stay out.

### C. External administrator dependencies
TUM-Hackathon organization **owner/admin**: approve Coworker workspace access (`PENDING` → `GRANTED`); confirm Seat eligibility (`taskSeatEligible` was `true`). Masumi/Sokosumi mentors: the USDM-on-preprod question; whether CLI 1.0.4 personal workspace is expected to work; Fixed vs Dynamic pricing for marketplace listing; mainnet whitelisting is not needed (preprod listings appear automatically per docs, [UNVERIFIED]).

### D. Completion criteria
* A real model reply and an execution-only Task `COMPLETED` (Task IDs recorded).
* ≥ 1 **paid** Task or MIP-003 job `COMPLETED` on preprod with: Task/job id, result text + report SHA-256, funds-locked tx hash, result-hash tx hash, settlement tx hash, **verified seller net receipt**, explorer links — all in `docs/EVIDENCE.md` as observed.
* The three agents registered once (no duplicates), `scripts/preflight.py` reports READY, MIP-003 `availability = available` for Agents 1–2.
* Website reachable on the server in `masumi` mode with a real payment path; all three workflows exercised for DE and IN in a browser; access restrictions re-checked.
* Public repo with README, Devfolio description and a ≤ 2.5-minute video script/recording based on real evidence (re-check the submission rules at `hackathon.tum-blockchain.com/prizes`; note the track page only listed generic rules, the paid-job requirement came from the team's notes).

---

## 10. Reasons behind decisions and failed attempts (avoid repeating)

* **Why three paid agents + one Coworker:** audit, lease check and disclosure are distinct sellable results with different prices and delivery; matching/NDA/joint calculation are stages of *one* result (Pool Access), so internal. The Concierge exists to give a language model a real job (parse free text → validated order, ask/decline, summarise) while keeping calculations deterministic.
* **Why Pool Access is not hireable from the marketplace:** it needs each party's identity, consent and signature; anonymous one-shot jobs would simulate that. `start_job` returns 400 with guidance; payments for it still need a registered agent identifier.
* **Why money only in the gateway:** one payment path, one idempotency story, no unpaid compute path; geo services are internal with bypass on.
* **Why Markdown for marketplace/Sokosumi, JSON for web:** the Task result text itself is what the quickstart hashes (raw); MIP-003 uses the MIP-004 escaped form; each hash covers exactly what is delivered. The embedded `report_sha256` ties them together.
* **Why TUM workspace:** CLI 1.0.4 personal path returned 404 (6.5).
* **Failed/blocked attempts:** (1) `sokosumi auth login` initially failed "OS credential vault is required" → cause: missing `secret-tool`; the user installed `libsecret-tools`; resolved. (2) WebFetch of the TUM prizes page did not contain Cardano track rules (only generic submission rules). (3) Sokosumi's logged-in UI was unreachable → docs/CLI skills were used instead. (4) `pkill -f "…dev.py"` inside a shell command kills that shell (exit 144) — use `[x]` patterns. (5) Eve refuses a custom model without `ZAI_CONTEXT_WINDOW_TOKENS`. (6) The original owner MVP's operator-only design was *not* exposed; replaced. (7) Docker was unavailable: compose is untested. (8) A full "pool deal" in the real stack produced a *negative* economic result — expected behaviour, documented honestly; do not "fix" it to look better.
* **Pitfalls found by tests:** oversized CSV raised an unhandled `csv.Error` (fixed); `replaceChildren(null)` renders the text "null" in the UI (filter children); deal rows exist in the escrow only after the first consent (gateway synthesises a `not_started` view).

*Last verified by the authoring agent on 2026-10-31. If anything in sections 6–7 disagrees with what you observe, trust your observation and update this file.*

---

## 11. Session 2 log — machine 2 (Windows 11, 2026-10-30/31 evening) — supersedes §0/§6 where they disagree

**Environment found [VERIFIED].** Windows, Node 22.23.2 system-wide (project needs 24 → portable Node 24.22.2 in `C:\Users\fandr\.agroland-tools\node_modules\node\bin\node.exe`, run it directly: `npm.cmd` puts its own Node first), Python 3.14.2 (`.venv-win`), Docker 29.6.2 (unrelated containers only — do not touch), **Sokosumi CLI 1.1.0** (not 1.0.4). With 1.1.0 the **Personal Workspace works** (`workspaces list --personal` → `hasPersonalWorkspace: true`); the §6.5 404 is a 1.0.4 problem. The archive's `.venv-dev`, `node_modules` and `state/` were Linux/machine-1 artifacts and are unusable here.

**Account resolution (§6.3) [VERIFIED + user decision].** The logged-in account is `01a186a0-…` (fedorovandriy2009@gmail.com), which owns the prototype vendor **Geo Pooler** and coworker **Land Audit Germany** (`01a18e91-38fc-7119-9e4e-adfd7c1dd666`); it is a member of TUM-Hackathon (role member). The machine-1 resources (`AgroLand` vendor, `AgroLand Concierge` `01a18eff-2268…`) belong to a *different* account and were not touched. On the user's explicit choice ("Repurpose Land Audit Germany") the prototype worker (PID 40092) was stopped and the coworker was **renamed to `AgroLand Concierge`** (slug stays `land-audit-germany`; CLI cannot change slugs). Its runtime key was already in this machine's credential vault and was reused (no new key issued). `agent/.env` now has `COWORKER_ID=01a18e91-…`, org id/slug empty (= Personal Workspace). The prototype's geo services on :8000/:8001 are still running (not ours; AgroLand's dev stack uses `--de-base 18000 --in-base 19000`).

**Model [VERIFIED].** OpenAI-compatible, from the machine's `OPENAI_API_KEY`, passed via process env only (never written to a file): `ZAI_BASE_URL=https://api.openai.com/v1`, `ZAI_MODEL=gpt-4.1-mini`, `ZAI_CONTEXT_WINDOW_TOKENS=128000`.

**Real Sokosumi Tasks (preprod, Personal Workspace, PAID_TASKS_ENABLED=false) [VERIFIED]:**
| Task id | Request | Result |
|---|---|---|
| `01a18f28-c334-7267-9d80-77be89c8a2f1` | "What can AgroLand do and what does each cost?" | COMPLETED; model answer from `coverage` tool, prices 1.00 / 2.00 / 3.00 tUSDM match `config/services.json` |
| `01a18f29-340b-7458-8279-b5bc967425cb` | "Audit a solar site at 52.0746, 12.7329 in Germany" | COMPLETED; quote only (Land Audit, 1.00 tUSDM, "nothing was run or charged"); gateway order count stayed 0 |
Follow-up comments on the second Task were answered as plain text (IN wind audit → would-order text; IN lease check → 2.00 tUSDM quote). These are **execution-only** checks: no payment, no registration, no on-chain transaction.

**Bugs found and fixed this session (all with tests; `scripts/test_all.sh` equivalents: gateway 31 passed, Node 27 passed, on Windows):**
1. `scripts/stack.py`: geo child processes got a PATH-only environment → Windows `WinError 10106` (sockets); now passes SYSTEMROOT etc. `scripts/dev.py` gained `--de-base/--in-base`.
2. `agent/sokosumi-cli.mjs` (new): Windows cannot `execFileSync('sokosumi')` (.cmd shim); worker/runtime now launch the CLI via `node <npm root -g>/@masumi_network/sokosumi/dist/bin/sokosumi.js` (override `SOKOSUMI_CLI_JS`). `sokosumi-runtime.mjs` accepted only `/skills` paths; now separator-agnostic.
3. Gateway `services.validate` accepted only `lat`/`lon` while the agent instructions and MIP-003 schema used `latitude`/`longitude` → the model could never produce a valid point. Now both are accepted; instructions say `lat`/`lon`, apply defaults, don't ask needless questions, and phrase the summary as a plan ("would order").
4. Worker posted the model's **raw JSON plan** as a comment reply on Tasks without an order; now rendered by `planner.describePlan` (a comment never creates an order).
5. Three POSIX-only Node tests made platform-aware. Repo hygiene: `agent/.eve` untracked (`git rm --cached`, `.gitignore`), **not committed**.

**State at the end of this session:** running locally (all dev-only): AgroLand dev stack `--unpaid` on :8080 (scratchpad state dir), Eve on :21949, **one** worker for the Concierge (journals in `agent/.local/`). Nothing committed or pushed. **Still not done:** payment service not running, no seller wallet check, no registration, no paid job, no Docker deployment, no browser pass of the remaining UI paths, `docs/EVIDENCE.md` still PENDING (execution-only Tasks above are not payment evidence).

**Payment prerequisites found on this machine (names/presence only):** prototype folder `C:\Users\fandr\Desktop\geo-pooler` has a `.env` with a Blockfrost key, a wallet seed phrase, ENCRYPTION_KEY/ADMIN_KEY/POSTGRES_PASSWORD, a Masumi API key and agent identifiers for the audit and escrow services (payment service expected at `localhost:3001`, **not running**); Docker image `masumi-payment-setup:0.29.0` exists locally; prototype audit server `https://audit.mrrobot.hackclub.app/health` answers `{"ok":true}`. Whether that wallet is funded, whether those agents are still registered, and whether the wallet is a throwaway are **unknown** — needs the user's go-ahead to start the payment stack and inspect (§9 step 5–6 gates unchanged).

### 11b. Payment setup (authorized by the user on 2026-10-31; stops before registration and any paid job)

**Done and verified [VERIFIED]:**
* Compose: `deploy/docker-compose.yml` now has the missing one-shot **`payment-setup`** (Prisma migrate + seed, release 0.29.0, `SEED_ONLY_IF_EMPTY`) and the payment service port is configurable (`MPS_PORT`; 3001 here is an SSH tunnel to `mrrobot@hackclub.app`, 3101 is used by another program). `docker compose config` is valid; `postgres`, `payment-setup`, `masumi-payment-service` were started for real (project `agroland`, volume `agroland_pg_data`, service on `127.0.0.1:38127`, health `ok`, V2 contract seeded, registry policy id `67ab0c92…`). The gateway/geo/caddy containers of the compose were **not** started (the dev stack runs from `scripts/dev.py`).
* **New dedicated seller wallet** (generated inside the pinned image with MeshWallet, mnemonic only in the git-ignored root `.env`; address `addr_test1qqym…crg536`, id `cmvvm9b9700094ativ7jc283p` in payment source `cmvvm9b9400044atiojlo8id0`, Web3CardanoV2, Preprod). **On-chain balance: never funded (Blockfrost 404).** The official quickstart says "Don't copy another project's wallet, registration, or task IDs", so the prototype wallet seed was **not** imported. Only the prototype's Blockfrost project key (valid on preprod) was reused.
* Wallet-scoped runtime key (canRead/canPay, **not** admin, Preprod only) created via `payment-registration.mjs key` → token in `agent/.local/mps-runtime.env` and root `.env` as `MPS_RUNTIME_TOKEN`; `SELLER_VKEY` set; `agent/docs/payment-state.json` written (IDs only). `.gitignore` now covers `agent/docs/{payment,registration}-state.json`.
* **Bug fixed (was the handoff's "UNVERIFIED" item):** the live OpenAPI (`GET /api-docs`) says top-level `AgentPricing` is forbidden for V2 and pricing belongs in `supportedPaymentSources[].pricing` as `{pricingType:'Fixed', fixed:[{asset, amount, decimals}]}`. `register-agents.mjs` sent `Pricing:[{unit,amount}]` and would have been rejected. Fixed via `v2FixedPricing` (tested, 4/4).
* `scripts/preflight.py` against the local stack lists exactly what is still missing: agent identifiers ×3, https public URL, gateway not in `masumi` mode (the dev stack on :8080 is `dev-unpaid`).

**Found on this machine [VERIFIED, public chain data]:** the prototype wallet holds ≈ 9,948.6 test ADA and **no tUSDM**; two prototype registry NFTs (audit + escrow agents) exist on-chain. The prototype's own payment-service database volume is gone from local Docker. An SSH tunnel `-L 3001:127.0.0.1:3001 mrrobot@hackclub.app` is open (the prototype's payment service on the server was not reachable through it when probed). Not touched.

**Exposure note:** the payment-setup log printed an auto-generated *purchase*-wallet mnemonic (unfunded) into this session's output. Do not fund or use that wallet; create the buyer wallet freshly when needed.

**Blocked on the user/external:** (1) test ADA for the seller address (faucet or Masumi dispenser need a browser/captcha; or explicitly authorize moving funds from the prototype wallet); (2) a **public https URL** for the gateway before registering (registry `apiBaseUrl` is immutable) → needs the deployment to the server and the user's go-ahead for registration (spends test ADA, immutable); (3) the tUSDM question — neither the TUM guide nor the quickstart README states the token or how a buyer obtains it; the Core buyer's funding is unverified; (4) a funded buyer (tUSDM or whatever Core uses) for the first paid job.

### 11c. Seller wallet funded (user confirmed in chat, 2026-10-31)
* **Funding tx (preprod, confirmed, block 5354981, fee 0.178 ADA):** `55876a8aae51db5bf044fe26a87ff946e000cabee57d350d48647afbb86aa4c6` — 1,000 tADA from the prototype wallet to the new seller wallet `addr_test1qqym…crg536`. Seller on-chain balance after: exactly 1,000 ADA (Blockfrost). Done in a throwaway container with the seed in process env only; the script aborted unless the derived address equalled the prototype's known address. No token (tUSDM) was moved or exists in either wallet.
* **Registration NOT done yet.** `register-agents.mjs plan` (nothing sent) shows the three V2 payloads matching the live schema (Fixed, `fixed[{asset=tUSDM unit, amount 1000000/2000000/3000000, decimals 6}]`). Missing input: the final **public https base URL** of the gateway (`apiBaseUrl = <URL>/masumi/<service>` is immutable once registered). Do not register against a temporary tunnel or a guessed hostname. Then: `AGENT_AUTHOR=… PUBLIC_BASE_URL=https://… node --env-file-if-exists=.env --env-file-if-exists=.local/mps.env register-agents.mjs register`, wait for `status`, copy the printed `AGENT_IDENTIFIER_*` into root `.env`, restart the gateway in `masumi` mode, rerun `scripts/preflight.py`.

## 11d. Hack Club deployment + registration (2026-10-31)
- Server `mrrobot@hackclub.app`, `/opt/agroland` (compose project `agroland`), public `https://audit.mrrobot.hackclub.app` (-> port 8000). SSH TCP forwarding is **prohibited** by the host, so the server's payment service is only reachable by running commands on the server (python3 over ssh, or `docker run --network host node:22-alpine` with scripts in `/opt/agroland-agent`).
- Server payment source `cmvvmo8tw00048qoz41dsd656`, selling wallet `cmvvmo8ty00098qozjutrs69b` (local `agent/docs/payment-state.json` now holds these). Wallet-scoped ReadAndPay runtime key created on the server and stored in `/opt/agroland/.env` (`MPS_RUNTIME_TOKEN`), gateway restarted.
- Masumi V2 API rejects `decimals` in Cardano fixed pricing (fixed bug in `registration-config.mjs`).
- Registrations submitted once (IDs in `/opt/agroland-agent/agent/docs/registration-state.json` on the server): land_audit `cmvvmzukz000201m46ud9mbkx`, lease_check `cmvvmzuox000701m4sqmeoaov`, pool_access `cmvvmzutz000c01m4s9irvepf`. State at last check: RegistrationRequested. DO NOT re-register; run `register-agents.mjs status` (same docker command) until confirmed, then copy `AGENT_IDENTIFIER_*` + `SELLER_VKEY` into `/opt/agroland/.env` and restart the gateway.

### 11d. Worker note (2026-10-31 ~01:30)
The worker I started (PID 34504, Node 24) exited with code 1 and no message (cause unknown). A worker (PID 36132) was started by another Claude session through system **Node 22** (`C:\Program Files\nodejs`, project needs ≥24) and now holds `agent/.local/worker.lock`. It is the only worker; I did not kill it and did not start another. Health-check Task `01a18f5c-3c61-723b-a828-6dd108dfb555` ("Which countries does AgroLand cover?") COMPLETED with a model answer, so it has working model/gateway settings. **Before any paid Task:** stop it, check `agent/.local/worker.lock`, and restart exactly one worker under Node 24 with `PAID_TASKS_ENABLED` set deliberately.

### 11e. Eve crash + gateway 500 (2026-10-31 ~01:50)
My Eve (Node 24) ended with exit 255 after a `get_report` tool call got `gateway 500`. Cause (gateway log): `GET /internal/orders/<unknown id>` called `engine.advance()`, which tried to journal an `advance_error` event for a non-existent order → SQLite `FOREIGN KEY constraint failed` → HTTP 500. **Fixed** in `Engine.advance` (returns for unknown ids; the endpoint now answers 404) + test `test_internal_get_unknown_order_is_404_not_500`; gateway suite orders 10/10. The running dev gateway on :8080 needs a restart to load it. Another Eve (PID 8076, started 01:52 by another session) is coming up; there must be one Eve on :21949. Not investigated: why the model supplied a non-existent order id, and whether an Eve tool error should be survivable instead of exiting the process.
