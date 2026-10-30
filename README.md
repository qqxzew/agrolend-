# AgroLand — agentic commerce on Cardano for land, leases and energy sites

AgroLand helps three kinds of customers work with land — **landowners**, **tenant farms** and **energy developers** — in **Germany and India**. You pay per result on **Cardano preprod** through **Masumi**; the same engine answers on our website and inside **Sokosumi**.

Built for the Cardano track of the TUM Blockchain & AI Hackathon (Munich, 30–31 Oct 2026).

> **Status in one paragraph.** The product, the shared execution engine, the three workflows (both countries), the website, the Masumi seller side, the MIP-003 agent API and the Sokosumi Coworker are implemented and tested locally. **No real Cardano payment, Masumi registration, Sokosumi Task or model call has been made yet** — those need accounts, keys, funded test wallets and your authorization (see [docs/DEPLOY.md](docs/DEPLOY.md)). Evidence fields in [docs/EVIDENCE.md](docs/EVIDENCE.md) are marked **PENDING**; nothing there is invented.

---

## 1. The agents (catalog)

Three paid services are registered in Masumi as separate agents; the language-model Concierge is the Sokosumi-facing Coworker. Everything else is an internal service (section 2).

### Agent 1 — Land Audit  (paid Masumi service)
| | |
|---|---|
| **Purpose** | Wind / solar due-diligence verdict for one parcel or site. Three things are reported separately: the **audit conclusion** (GO / CONDITIONAL_GO / NO_GO + score), a **preliminary geometric signal** (Magdeburg A14 corridor, green/yellow/red — geometry only), and **data quality** (which sources answered; an unavailable source is a limitation, never a pass). Ownership, planning permission and grid-connection availability are *never* claimed. |
| **Input** | `country` (DE/IN), `project_type` (solar/wind/hybrid), one of: a saved parcel, a drawn polygon, or `latitude`+`longitude`(+`radius_m`); India: optional `survey_number` (format-checked only). |
| **Output** | Canonical JSON report + Markdown rendering + SHA-256. |
| **Relationships** | Used by the owner flow (a delivered audit is attached to a listing) and the developer flow. Runs the internal audit engines (DE `services/geo/app`, IN `services/geo/india/audit`) and, for Magdeburg ALKIS parcels, the local corridor screening (`gateway/agroland/alkis.py`). |
| **From our app** | Owner → *Audit a parcel*; Developer → *Sites*. `POST /api/orders {service:"land_audit"}` |
| **From Sokosumi** | (a) Marketplace: MIP-003 agent at `/masumi/land_audit` (hire as a Job); (b) Coworker Task: describe the site in text, the Concierge plans and orders it. |
| **Paid Masumi service** | Yes — **1.00 tUSDM** (`config/services.json`). |
| **Configuration** | `AGENT_IDENTIFIER_LAND_AUDIT`, geo keys, `config/services.json`. |
| **Verification** | `gateway/tests/test_orders.py`, live runs in [docs/VERIFICATION.md](docs/VERIFICATION.md). Result hash proves the stored report is unchanged, not that its data is true. |

### Agent 2 — Lease Check  (paid Masumi service)
| | |
|---|---|
| **Purpose** | Compares a tenant farm's **lease contracts**, the **official parcel record** (ALKIS extract / 7-12 Record of Rights) and the **fields actually farmed**. Findings: paid-but-unfarmed land, billed area above the record, rent above a labelled benchmark, expiring leases. It separates **identified** (follows from your own documents), **negotiable** (an opportunity, not a loss) and **achieved** (only what *you* record after acting — the engine never computes it). Produces a calendar `.ics` with rent and expiry reminders. |
| **Input** | `country`; data source: the labelled demo farm, saved CSV upload (`contracts`, `cadastre`, `fields`), or inline CSV (MIP-003). |
| **Output** | Report (every finding carries numbers and source rows), Markdown, `.ics`, SHA-256. Delivered **only if every finding is recomputed from the source rows and passes** (`verify_report`). |
| **Relationships** | Standalone. Country packs: DE (ha, EUR) and IN (acre, INR). One maintained engine: `gateway/agroland/farm.py` (identical numbers to the original `case3-farm` JavaScript on the German data: €1,440 identified, €720 negotiable). |
| **From our app** | Farm → *Lease Check*. `POST /api/orders {service:"lease_check"}` |
| **From Sokosumi** | MIP-003 `/masumi/lease_check`; or a Coworker Task ("check my leases, India demo"). |
| **Paid** | Yes — **2.00 tUSDM**. |
| **Configuration** | `AGENT_IDENTIFIER_LEASE_CHECK`. |
| **Verification** | `gateway/tests/test_farm.py` (parity, forged-report rejection, CSV validation, calendar syntax), `test_listings.py::test_farm_upload_and_outcomes`. |

### Agent 3 — Pool Access  (paid Masumi service; started on the website)
| | |
|---|---|
| **Purpose** | Safe introduction between two energy developers whose sites are within 1.5 km: **anonymous teaser → both consent → both payments locked → NDA signed by each party for itself → disclosure of the counterpart + a preliminary joint calculation + draft Pooling Agreement and Grid Application (PDF)**. One payment per party covers disclosure *and* calculation (no double charge). If the deal is declined/expires, no result hash is submitted and the buyer uses the protocol refund. |
| **Input** | A `match_id` from the matcher (created by registering sites in the pool). |
| **Output** | Revealed counterpart package, joint plan (shares in basis points summing to 10 000, turbine layout, NPV), two PDFs with hashes. |
| **Relationships** | Internal services: matcher → escrow/NDA → architect (DE and IN stacks). Proximity of two sites never proves a continuous block or an economic benefit — the report says so. |
| **From our app** | Developer → *Sites* → add to pool → *Matches & deals*. |
| **From Sokosumi** | **Not hireable as an anonymous one-shot job**: it needs each party's identity, consent and signature. Its MIP-003 `/masumi/pool_access` answers availability and `start_job` returns 400 with the website path. This is a deliberate platform boundary. |
| **Paid** | Yes — **3.00 tUSDM per party** (longer windows: pay 48 h, deliver 7 days). |
| **Configuration** | `AGENT_IDENTIFIER_POOL_ACCESS`. |
| **Verification** | `gateway/tests/test_pool.py` — runs against the **real** matcher, escrow and architect services for **both DE and IN**: payment gate before the NDA, hash-checked signatures, no delivery before both sign, access control for outsiders, decline path. |

### Agent 4 — AgroLand Concierge  (Sokosumi Coworker, language model; not a paid registration)
| | |
|---|---|
| **Purpose** | The LLM-facing face of AgroLand in Sokosumi. It reads a free-text Task, uses real tools (`coverage`, `validate_order`, `get_report`) to plan a valid order, asks a clarifying question instead of guessing, declines out-of-scope work, and later writes a plain-language summary of the delivered report (labelled as AI text, **not** part of the hashed deliverable). |
| **Input / output** | Task text → either an execution-only answer (clarify / decline / info / quote when payments are off) or **one** paid order whose exact report text is the Task result. |
| **Relationships** | Calls the same gateway as the website (`/internal/*`). One Task = at most one order; payment goes through Sokosumi Core (`masumiPayment` event), so nothing is charged twice. |
| **Invocation** | Create a Task for the Coworker in Sokosumi (`agent/worker.mjs` polls). |
| **Paid** | The order inside it is (Agent 1 or 2 price). The Coworker itself is not a separate registry entry. |
| **Configuration** | `agent/.env` (`ZAI_*` model, `COWORKER_ID`, `AGROLAND_INTERNAL_KEY`, `PAID_TASKS_ENABLED`). |
| **Verification** | `agent/*.test.mjs` (25 tests: planner validation, paid-order journal with fake gateway/Core, no-replay, quickstart tests). **Model replies and Tasks: PENDING (needs a model key and Sokosumi login).** |

---

## 2. Architecture

```
                 Browser (web/)                 Sokosumi marketplace / Coworker Tasks
                      │                                   │
                      ▼                                   ▼
        ┌────────────────────────── Gateway (gateway/agroland, FastAPI) ───────────────────────────┐
        │  workspaces (token per browser) · parcels · listings · farm data · pool orchestration     │
        │  ORDER ENGINE: quote → pay → run → deliver → hash → submit → confirm → settle            │
        │  /api/*  (website)   /masumi/<service>/*  (MIP-003)   /internal/*  (Coworker worker)      │
        └───────┬───────────────────────────┬──────────────────────────────┬───────────────────────┘
                │ internal keys, loopback   │                              │ seller side
                ▼                           ▼                              ▼
   Geo services ×8 (services/geo)      SQLite state            Masumi Payment Service (+ Postgres)
   DE: audit · matcher · escrow · architect                      → Cardano preprod, Blockfrost verify
   IN: audit · matcher · escrow · architect
```

* **One execution system.** The website, MIP-003 buyers and the Coworker all create the *same* order through `orders.Engine`; the report is produced once, from the same runner. Channels differ only in how the deliverable is *packaged and hashed*: website → canonical JSON, MIP-003 → Markdown (MIP-004 hash), Sokosumi Coworker → Markdown (official-quickstart raw hash). Each hash covers exactly what is delivered, and every report embeds the SHA-256 of the canonical report so results can be compared across channels.
* **Money is handled in one place.** The geo services run with payment bypass **on** and are reachable only on the private network; only the gateway's orders touch Masumi. Before it sends any external write the engine journals it; a write whose outcome is unknown freezes the order for inspection instead of being replayed (no duplicate payment requests after refresh/restart).
* **What runs where.** *Our server*: everything above. *Masumi (on-chain)*: agent registry entries (metadata NFT) and the payment contracts. *Sokosumi*: discovery, hiring and the Coworker UI. Registration is **not** code hosting: a Sokosumi listing is backed by `/masumi/<service>` on our server.
* **Payment facts are four separate things:** report ready · funds locked (confirmed on-chain) · result hash confirmed on-chain · seller paid out. The UI and API never collapse them.
* **Access control.** Every parcel, document, order, listing, farm dataset and deal is bound to a workspace id and filtered by it; foreign ids answer 404. Owner documents are owner-only. Listings expose an allow-list (region, area, price, audit summary); the exact boundary goes only to a developer the owner accepts. Workspaces have **no passwords** (a browser-held secret token) — fine for a demo, not strong authentication. Public-demo hardening: per-IP workspace and per-workspace order rate limits, request-size limits (12 MB body, 1 MB per CSV), a 200-parcel cap, a Content-Security-Policy without inline scripts, frame/permission headers, same-origin checks on writes.

### Internal services (not presented as agents)
`services/geo/app` (DE audit engine), `services/geo/india/audit` (IN audit engine), matcher (neighbour search, anonymous teasers), escrow/NDA (consent, NDA PDF with hash-checked acceptance, reveal), architect (joint layout, Shapley/area/revenue split, draft agreement and grid-application PDFs) — each for DE and IN; the order engine, farm engine, ALKIS corridor screening, listings, MIP-003 router.

### Design decisions (why three agents + one Coworker)
Three user workflows ≠ three technical agents, but here the three *sellable results* are distinct (an audit, a lease check, a disclosure) and are priced and delivered differently, so each is its own Masumi agent. Matching, NDA and the joint calculation are *stages of one paid result* (Pool Access) and are therefore internal. The Concierge exists because a language model has a real job in Sokosumi: turning free text into a valid, priced order and explaining results; all calculations stay deterministic.

---

## 3. Run it

### Local, no Docker, no payments (developers only)
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python scripts/dev.py --unpaid            # 8 geo services + gateway + website on http://127.0.0.1:8080
```
`--unpaid` sets `AGROLAND_PAYMENT_MODE=dev-unpaid`: **every order and result is labelled UNPAID in the API and in a red banner; no Cardano transaction exists.** Without `--unpaid` the gateway runs in `masumi` mode and needs the payment setup in [docs/DEPLOY.md](docs/DEPLOY.md).

Demonstration data: `.venv/bin/python scripts/seed_demo.py --pool` (workspaces for both countries; real audits, takes minutes), then `scripts/walk_deal.py --country DE|IN` walks a full two-party deal.

### Tests
`scripts/test_all.sh` runs everything below (offline; no accounts, keys or payments).

```bash
.venv/bin/python -m pytest gateway/tests -q            # 30 tests, ~60 s (starts real geo services as subprocesses)
(cd services/geo && for t in tests/test_*.py; do ../../.venv/bin/python $t; done)   # original service suites
(cd agent && npm ci && npm test)                       # 25 tests, Node 24
(cd agent && AGROLAND_URL=… AGROLAND_INTERNAL_KEY=… npm run e2e:fake)   # real Eve + tools + gateway, scripted stand-in model
```

### Production on the team's server → [docs/DEPLOY.md](docs/DEPLOY.md)
`deploy/docker-compose.yml` (gateway, 8 geo services, Postgres, Masumi payment service, Caddy TLS) + systemd units for the Coworker worker; `scripts/preflight.py` lists what is still missing; `scripts/evidence.py` exports real payment evidence.

---

## 4. Country coverage (honest)

| | Germany | India |
|---|---|---|
| Parcels | Open ALKIS fragment, Magdeburg / Sachsen-Anhalt (191 agri parcels, real geometry, **no owner data**); drawn outlines anywhere in DE | Illustrative demo rectangles at real coordinates in Gujarat and Andhra Pradesh (**not survey boundaries, survey numbers invented**); drawn outlines anywhere in IN |
| Audit sources | BKG VG250, OSM Overpass, BfN (EEA fallback), PVGIS, Open-Meteo/DWD, Copernicus DEM; ALKIS WFS only for NRW/Brandenburg | Nominatim, OSM Overpass, PVGIS 5.3, Open-Meteo ERA5, Copernicus DEM. State knowledge only for **Gujarat and Andhra Pradesh** |
| Corridor signal | A14 200 m / 500 m (OSM carriageway **axis**, not the legal outer edge) | none |
| Lease Check | EUR, hectares, ALKIS record, Gemarkung-Flur-Flurstück | INR, acres, Record of Rights (7/12), Village-Survey no. |
| Pool documents | German NDA (NDA-DE-1.0), Flächenpoolvertrag, Netzanschlussbegehren | English NDA (NDA-IN-1.0), Land Pooling Agreement, Grid Connectivity Application |
| Not provided | ownership/Grundbuch lookup, Bavaria ALKIS, planning-permission or grid-availability confirmation, Flächennutzungsplan/wind zones | ownership/title verification (no public API), non-GJ/AP state rules, protected-area completeness (OSM-based, completeness unmeasured) |

Demonstration datasets are labelled "demo" in data, API and UI. Unavailable sources are shown as limitations. The Indian module's rules and the NDA/contract templates are machine-generated drafts: **have an advocate/lawyer review them** before any real use.

---

## 5. Skills and documentation used

* **Cardano Developer Skills** (`suggest-tooling`, `query-chain`): used to choose the stack (Masumi seller flow; **Blockfrost preprod** to verify transactions independently, `gateway/agroland/masumi.py:verify_tx_on_blockfrost`, `agent/settlement.mjs`; x402 evaluated — see Not implemented).
* **Masumi / Sokosumi documentation** (`masumi.network/dev/...`), the official TUM quickstart and its `AGENTS.md`, and the **Sokosumi CLI 1.0.4 bundled skills** (`sokosumi skills`, installed locally). I could not open the logged-in Sokosumi interface (sign-in required), so I used the documentation: MIP-003 endpoints, tUSDM pricing, listing rules ("preprod listings appear automatically when the agent is registered with tUSDM pricing and is online"), registration being immutable, Coworker runtime/receipt commands.
* Not done: `npx skills add … masumi` (the install command was not run; the official guide and quickstart were read directly) — see [docs/VERIFICATION.md](docs/VERIFICATION.md).

---

## 6. Implemented / awaiting access / not implemented

**Implemented and verified (locally)** — details and evidence in [docs/VERIFICATION.md](docs/VERIFICATION.md): shared order engine with idempotent payment journal; Masumi seller client with fake-payment-service tests of every transition; MIP-003 API; all three workflows for DE and IN (Pool Access verified against the real matcher/escrow/architect for both countries); live DE and IN audits through the gateway; website (landing + app) checked in a browser; Node worker/planner/paid-order state machine tested with fakes; deployment files and preflight.

**Ready but awaiting external access or authorization**: Sokosumi sign-in, Vendor/Coworker, model reply and execution-only Task check; payment service + funded wallets; Masumi registration (immutable, spends test ADA); paid preprod job + tx hash; Sokosumi TUM-workspace grant; public domain/TLS; Docker/compose first start. Exact steps: [docs/DEPLOY.md](docs/DEPLOY.md).

**Not implemented**: x402 pay-per-request path (not needed for qualification; the Masumi paid-job path is the integration); CIP-30 browser-wallet payment on the website (the website supports paying from a Masumi/Sokosumi wallet using the payment identifier, or an operator-funded demo wallet); qualified e-signatures; ownership verification; Bavaria data; strong user authentication; an Indian farm record lookup.

---

## 7. Layout
```
config/services.json   single source of truth: services, prices, payment windows
gateway/               API, order engine, services, MIP-003, tests
services/geo/          internal audit/matcher/escrow/architect services (DE + IN) from geo-pooler (secrets and venv removed)
web/                   landing page + app (no build step; Leaflet vendored)
agent/                 Eve Concierge, Sokosumi worker, paid-order machine, registration helpers (from the official quickstart, pinned deps)
data/                  ALKIS fragment, India demo parcels, farm datasets (DE, IN)
deploy/  scripts/  docs/
```
Raw inputs (`*.tar`, `_src_*`) are git-ignored: the supplied `geo-pooler.tar` contained a live `.env` with a wallet seed — it was not copied anywhere in this project. **If that seed was ever used for anything beyond a throwaway test wallet, treat it as compromised.**
