# Deploying AgroLand on the team's server — what you must provide, what to run

Nothing here has been executed against your server, your accounts or the chain. Every step that spends funds, writes a public registry entry, signs in to an account or changes the live server needs **your explicit go-ahead**. API keys alone are not enough: several steps need an account sign-in, an approval by someone else, or funded test wallets.

## A. What the team must provide or do (checklist)

| # | Need | Why / notes |
|---|---|---|
| 1 | **Server** (Linux, ≥ 4 GB RAM, Docker + Compose, ports 80/443) and a **domain** with an A/AAAA record to it | Masumi buyers and Sokosumi must reach `https://<domain>/masumi/<service>`; `/internal/*` is hidden by Caddy |
| 2 | **Node.js 24** on the host and **Sokosumi CLI 1.0.4** (`npm i -g @masumi_network/sokosumi@1.0.4`) | The worker runs on the host because the CLI keeps the Coworker key in the OS credential vault |
| 2b | **`libsecret-tools`** (`secret-tool`) and a running Secret Service (GNOME Keyring) for the user running the CLI | Without it `sokosumi auth login` stops with "OS credential vault is required" (hit on the authoring machine; fixed by `sudo apt install libsecret-tools`) |
| 3 | A **Sokosumi preprod account** (https://preprod.sokosumi.com/signup) and an **OAuth sign-in** by you: `sokosumi --preprod auth login` | Interactive; I cannot do this for you. (The Sokosumi *MCP* server also uses OAuth — no API key.) |
| 4 | Membership in an **organization**, then a **Vendor** (one self-service Vendor per account) | Needed to register a Coworker |
| 5 | A **model API key** for any OpenAI-compatible provider (`ZAI_API_KEY`, `ZAI_BASE_URL`, `ZAI_MODEL`, `ZAI_CONTEXT_WINDOW_TOKENS`) | The Concierge is a language-model agent |
| 6 | **Blockfrost preprod project id** | Independent transaction verification; used by the payment service too |
| 7 | **A dedicated seller wallet** (new mnemonic, test funds only) in the Masumi payment service + **test ADA** (faucets: docs.cardano.org/cardano-testnets/tools/faucet or dispenser.masumi.network) | Registration and result submission cost ADA fees. Never reuse another project's wallet |
| 8 | **tUSDM for the buyer** — see "Open question: which token" | Sokosumi agents must settle in tUSDM; the guide says USDM is "not available" on preprod — you must confirm how to obtain it |
| 9 | Authorization for **Masumi registration** (3 agents) | Registry entries cannot be edited: changing a price later = deregister + register again |
| 10 | **Workspace approval** if running in the TUM workspace | `workspaces list --json` for id/slug, `coworkers connect`, an owner/admin must approve (`PENDING` → `GRANTED`) |
| 11 | Decide who may see the public demo | Workspaces have no passwords; put a basic-auth/IP allowlist in Caddy if the demo must be closed |

### Open question: which token (needs your decision)
`config/services.json` prices in **tUSDM** (preprod unit `16a55b2a…745553444d`, 6 decimals) because the official quickstart and the Sokosumi listing guide require USDM settlement. The Masumi *top-up* guide, however, states USDM is not available on preprod and only test ADA is needed. Before spending time on wallets, check with the Masumi engineer/mentors which is true for the Sokosumi Core buyer. The token lives in one place (`payment.token`); if you must use ADA instead, change it there and re-check the Core payload constraints in `agent/paid-order.mjs`/`/internal/orders/{id}/core-payload` (the quickstart hard-codes 1 tUSDM; our code reads prices from the catalog).

## B. Steps (in order). Stop at each marked gate

### B1. Configure and start the base stack
```bash
git clone <repo> /opt/agroland && cd /opt/agroland
cp .env.example .env && chmod 600 .env   # add OPENAI_API_KEY=… so the home-page assistant answers (optional; never commit .env)
# fill: AGROLAND_PUBLIC_URL, AGROLAND_DOMAIN, POSTGRES_PASSWORD, ENCRYPTION_KEY, ADMIN_KEY, BLOCKFROST_API_KEY_PREPROD,
#       SELLING_WALLET_PREPROD_MNEMONIC (dedicated test wallet), and random keys:  for k in AGROLAND_INTERNAL_KEY GEO_DE_INTERNAL_KEY GEO_DE_ESCROW_KEY GEO_DE_ARCHITECT_KEY GEO_IN_INTERNAL_KEY GEO_IN_ESCROW_KEY GEO_IN_ARCHITECT_KEY; do echo "$k=$(openssl rand -hex 24)"; done
docker compose -f deploy/docker-compose.yml --env-file .env config   # first time: validate
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
python scripts/preflight.py --url http://127.0.0.1:8080          # lists what is still missing
```
The compose file was written for this repo but **not started anywhere yet** (no Docker on the authoring machine). For `AGROLAND_PAYMENT_MODE` start with `masumi`; the gateway refuses to create payment requests until agents are registered, so it is safe before B3.

### B2. Payment service (Masumi, seller side)  — GATE: funds and secrets
The compose service runs `masumi-payment-service:0.29.0`. The image cannot run its own Prisma migration/seed; the geo-pooler prototype built the same release from source for a one-shot setup (see its `payment-setup` service). Follow the current Masumi docs ("Install Masumi Node") to migrate/seed, then:
1. Open the admin UI through an SSH tunnel (`ssh -L 3001:127.0.0.1:3001 server`, port is loopback-only).
2. Note the dedicated selling wallet id, address and the payment source id; save them in `agent/docs/payment-state.json` as `{"sourceId":…,"walletId":…,"sellerAddress":…}` (git-ignored).
3. Fund the selling wallet with test ADA.
4. `cd agent && npm ci && cp .env.example .env` (fill), put `ADMIN_KEY=…` in `agent/.local/mps.env` (chmod 600), then `npm run mps:key` → writes a **wallet-scoped ReadAndPay** key to `agent/.local/mps-runtime.env`. Copy that token to the gateway `.env` as `MPS_RUNTIME_TOKEN`.

### B3. Register the three agents — GATE: spends ADA, public and immutable
```bash
cd agent
AGENT_AUTHOR="<your name>" PUBLIC_BASE_URL=https://<domain> node --env-file=.env register-agents.mjs plan      # review exactly what is sent
npm run register                                                      # only after you approve
npm run register:status                                               # repeat until the state is registered (5–15 min on preprod)
```
Copy the printed `AGENT_IDENTIFIER_*` and `SELLER_VKEY` lines into the gateway `.env`, then `docker compose … up -d gateway`. **Check first:** the `pricing` block of a *Fixed* price is marked UNVERIFIED in `register-agents.mjs`; confirm the field names against the payment service OpenAPI (`/api/v1/…` docs) before the first `register`. Then `python scripts/preflight.py` must show `/masumi/<service>/availability = available` for Agents 1 and 2. On preprod, listings with tUSDM pricing appear in Sokosumi automatically once online and health-checked.

### B4. Sokosumi Coworker — GATE: account sign-in
```bash
sokosumi --preprod auth login && sokosumi --preprod auth whoami --json
sokosumi --preprod workspaces list --json ; sokosumi --preprod vendors me --json ; sokosumi --preprod coworkers list --scope owned --json   # reuse what exists
# create only if nothing suitable exists (and you agree):
sokosumi --preprod coworkers register --personal --vendor-id VENDOR_ID --name "AgroLand Concierge" --capability tasks --json
sokosumi --preprod coworkers api-key COWORKER_ID --json | sokosumi --preprod runtime key-import --coworker-id COWORKER_ID --api-key-stdin   # key goes to the vault, never a file
```
Put `COWORKER_ID` in `agent/.env`; keep `PAID_TASKS_ENABLED=false`.

> **Measured on 2026-10-30 (CLI 1.0.4, signed in, read-only calls):** `tasks list --organization-slug <TUM slug>` works and `workspaces check <ORG_ID>` returns `taskSeatEligible: true`, but `workspaces list --personal` fails with HTTP 404 `route_not_found` on `/v1/users/me/workspace-access` — the route the geo-pooler notes said no longer exists. So the **Personal Workspace path of 1.0.4 is currently unreliable** (`coworkers register/connect --personal` use the same user-workspace endpoint). The organization path (TUM-Hackathon) appears to work. Decide with the Masumi/Sokosumi mentors: use the TUM organization workspace directly, or try CLI 1.1.0 for the personal test. Nothing was created in Sokosumi to find this.
>
> Known conflict to test, not assume: the geo-pooler notes say CLI 1.0.4 calls an API route that no longer exists and recommend 1.1.0; the TUM guide and quickstart pin **1.0.4**. Test 1.0.4 first (`sokosumi --version`, then the Task below). If it fails, report the error before changing versions.

### B5. Verify before any payment (as required)
```bash
cd agent && npm start        # terminal 1: Eve agent (needs the model env)
npm run worker               # terminal 2; wait for "Continuous worker running"
```
1. **Model reply:** create a Task asking "What can AgroLand do and what does each cost?" — the Concierge should answer from `coverage` (execution-only, no payment).
2. **Execution-only Coworker Task:** `sokosumi --preprod tasks create --personal --coworker-id COWORKER_ID --name "Quote" --description "Audit a solar site at 52.0746, 12.7329 in Germany" --status READY --json` → with `PAID_TASKS_ENABLED=false` the Task completes with a **quote** (service, price) and nothing is charged. Confirm `COMPLETED`, then send a follow-up comment and check the reply.
Stop here and tell me; payment setup starts only after you authorize it.

### B6. Enable payments and run one paid job — GATE: you authorize
1. Set `PAID_TASKS_ENABLED=true` (agent) and restart the worker. Gateway is already in `masumi` mode.
2. Create a Task (e.g. the Land Audit above). Sequence you will see: order created → payment requested (`masumiPayment` event) → funds locked (confirmed) → report delivered → Task `COMPLETED` with the exact report text → result hash confirmed → seller withdrawal.
3. Evidence: `python scripts/evidence.py --write docs/evidence/orders.json`, plus `agent/.local/evidence/<TASK_ID>.json` (seller net receipt verified through Core receipt + Blockfrost). Verify the seller's **net receipt** before submitting. Fill [EVIDENCE.md](EVIDENCE.md).
4. Optional: hire Agent 1/2 from the Sokosumi marketplace as a Job (MIP-003 path), or open the website, create a workspace and pay with a Masumi wallet using the payment identifier shown in the order (or an operator-funded demo wallet: `BUYER_MPS_URL/BUYER_MPS_TOKEN`).

### B7. TUM workspace (after the personal test passes)
`sokosumi --preprod workspaces list --json`; connect with `coworkers connect COWORKER_ID --vendor-id … --workspace-id <ORG_ID>`; `workspaces check`; continue only when `taskSeatEligible` is `true` and access is `GRANTED`. Set `SOKOSUMI_ORGANIZATION_ID` and `SOKOSUMI_ORGANIZATION_SLUG` together, restart the worker, create Tasks with `--organization-slug`. Finish active Tasks and pending receipt checks before switching.

## C. Operations
* **Persistent state:** volumes `gateway_data` (SQLite + documents + pool PDFs), `geo_data`, `pg_data` (payment service), `caddy_data`. Back up with the stack stopped: copy the volumes. Losing `ENCRYPTION_KEY` makes the payment service wallets unreadable.
* **Update:** `git pull && docker compose -f deploy/docker-compose.yml --env-file .env up -d --build`. Orders in flight survive a restart: their payment journal resumes; an order frozen at `*-uncertain` is deliberately never replayed — inspect it in the payment service, then decide.
* **Diagnose:** `curl localhost:8080/api/health` (geo readiness, registration flags), `docker compose logs gateway`, `python scripts/preflight.py`. Order events are in `GET /api/orders/{id}`.
* **Credential vault on a server:** the Sokosumi CLI uses the OS vault; on a headless host you need a Secret Service (e.g. `gnome-keyring` + `dbus-run-session`) for the worker user. Verify `sokosumi --preprod runtime key-import` works for that user before relying on systemd. Never put the Coworker key in `.env`.
* **Rate limits are per process.** Set `AGROLAND_TRUST_PROXY=true` only behind Caddy. Caddy limits request bodies to 12 MB; add `rate_limit` (Caddy plugin) or a firewall rule if you expect abuse.
* **Public-demo hygiene:** the geo services are loopback/private only; the gateway never returns another workspace's data (tested); keep `AGROLAND_PAYMENT_MODE=masumi`; use only fictional farms/owners (GDPR); the local single-operator build of the original owner MVP was **not** exposed — its listings/documents now live behind per-workspace access control.
* **Known dependency findings:** the quickstart's `npm audit` reports 3 findings (eve, undici, zod). Versions stay pinned as required; review before exposing the worker (it only makes outbound calls and binds Eve to 127.0.0.1).
