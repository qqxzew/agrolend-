# Verification record — what was actually run (2026-10-30, local machine, Python 3.14.4, Node 24.22.2)

## Implemented and verified

| Area | Check | Result |
|---|---|---|
| Gateway | `pytest gateway/tests` | **30 passed** (~60 s). Includes: order engine (idempotency, no duplicate payment request on refresh, journal freezes on uncertain writes, failed execution is not delivered), per-user access control, country mismatch, MIP-003 start/status/hash rules, Sokosumi-channel hashing, owner listing lifecycle (consent, allow-list, interest, controlled disclosure, revocation, owner-only documents) for DE and IN, farm CSV upload and recorded outcomes |
| Payment state machine | `test_orders.py::test_masumi_path_with_fake_payment_service`, `test_mip003.py` | Passes **against a TESTING mock of the Masumi payment service**: nothing runs before funds are locked; "report ready", "result hash confirmed" and "seller paid out" are separate; submitted hash equals the hash of the delivered text. **This is not evidence of a real payment.** |
| Pool workflow | `test_pool.py` (4 cases) | Runs against the **real** matcher, escrow/NDA and architect services (subprocesses) for **DE and IN**; only the audit is stubbed. Covers: registration, duplicate rejection, anonymous teaser, outsider denied, consent needs profile, no order before both consent, NDA locked until both payments are locked, hash-checked signature, no delivery after one signature, delivery after both, PDFs, decline path |
| Original services | `services/geo/tests/test_*.py` (audit/payment flow, matcher, escrow, architect — DE and IN) | All pass in the copied tree (run before any change to them) |
| Farm engine | `test_farm.py`; JS original `node --test` (14/14) | Python generic engine gives identical findings and totals to the original JS on the German data (5 findings; €1,440 identified; €720 negotiable); forged reports fail recomputation; Indian demo: ₹4,60,800 identified, ₹1,54,000 negotiable |
| Node layer | `cd agent && npm test` | **25 passed**: planner JSON validation, order re-validation, paid-order stages with a **fake** gateway and fake Core (single order per Task, exact result text, no replay of uncertain writes, foreign Coworker rejected) + the official quickstart tests. Eve boots and loads the three tools with a dummy model endpoint (no model call made) |
| Live data, through the gateway | Land Audit order, unpaid dev mode | DE (Magdeburg ALKIS parcel, solar): **GO 95**, geometric signal green, all sources answered, 38 s. IN (Gujarat demo site, wind): **CONDITIONAL_GO 80**, 111 s, warnings: title not verified, OSM completeness, protected-area screen OSM-based |
| Live pool deals | `scripts/walk_deal.py` on the running stack, real audits via the matcher, two identities | DE and IN: teaser → consent → both orders → NDA hash → both signed → disclosure → plan → 2 PDFs. Real result: **joint project not viable** (DE: NPV −€1.82 M, no substation within 10 km in the audit data; IN: NPV −₹31.4 M), pooling not beneficial → split falls back to the area key (50/50) with warnings. This is the model working, not a failure |
| Website | In-app browser: landing page; workspace creation; Lease Check DE end-to-end incl. result persisting after reload; owner map with real ALKIS parcels and selection; developer deals view; phone-width layout (375 px) | Worked. Bugs found and fixed during these checks: stray "null" text, result card not updating, table overflow |
| Secrets | Repo scan | `.env` of the supplied geo-pooler archive (wallet seed, keys) not copied; `.env.example` files contain placeholders only; `.gitignore` covers `.env`, `state/`, `.local/`, tarballs |

## Hardening added and tested (no accounts needed)
`test_hardening.py`: workspace-creation and order rate limits (per IP / per workspace), oversized body and CSV rejected, parcel cap, CSP present on pages and absent on the API, no inline scripts, cross-origin writes blocked, **restart-resume** (a second app on the same state directory finishes a waiting order without creating another payment request). The tests found and fixed one real bug: an oversized CSV raised an unhandled parser error (HTTP 500). In-browser check with the CSP: landing prices, app, map tiles and portfolio all load.

## Sokosumi / Eve checks done without payment credentials (2026-10-30)
| Check | Result |
|---|---|
| `sokosumi --preprod auth login` (OAuth, user completed in browser) | Signed in after `libsecret-tools` was installed. Account seen: one that is a member of **TUM-Hackathon** only; **no Vendor, no Coworker**; whether it is the team's intended account is unconfirmed. Nothing created |
| CLI 1.0.4 read-only routes | `tasks list --organization-slug …` OK; `workspaces check` OK (`taskSeatEligible: true`); **`workspaces list --personal` → 404 route_not_found** (see DEPLOY.md B4) |
| `npm run e2e:fake` (agent/e2e) | Real Eve runtime + the three real tools + real gateway, with a **scripted stand-in for the model**: valid site → priced order plan (1.00 tUSDM); site outside Germany → clarification from the gateway's validation; missing location → question. **Proves wiring only: no real model reply has been made.** |

## Sokosumi resources created (2026-10-30, with the user's go-ahead for the TUM workspace)
Vendor `AgroLand` (`01a18eff-17c7-766b-a3ec-b5d0aaa90364`), Coworker `AgroLand Concierge` (`01a18eff-2268-705c-acb4-c0d803804044`, capability `tasks`), connected to **TUM-Hackathon** (org `01a17942-e6dd-724f-bae6-458b6a0f715a`, slug `tum-hackathon-u4ve65`). Workspace access is **PENDING**: a TUM workspace owner/admin must approve; then re-run `coworkers connect` (never `register`) until `GRANTED`. Runtime key imported into the OS vault (`stored: true`), not written to any file. Reuse these ids; do not create replacements.

## Ready, but needs accounts, keys, funds or authorization (NOT verified)
* Real Cardano preprod payment, funds-locked / result-hash / settlement transactions, Blockfrost verification code against live data.
* Masumi payment service start/migration, wallet funding, agent registration (the *Fixed* pricing field names are unverified against a live service), MIP-003 `availability = available` after registration.
* Sokosumi: Vendor/Coworker creation (blocked on account confirmation and the personal-workspace issue), model reply, execution-only Task, paid Task, receipt, TUM workspace grant, follow-up comment handling.
* Docker compose first start on the server (no Docker on the authoring machine; the file parses as YAML only). systemd units, Caddy TLS.
* Demo wallet purchase path (`/api/orders/{id}/pay-demo-wallet`): payload mirrors the quickstart's Core payload; untested against a live payment service.

## Not implemented
x402 paid-request path; CIP-30 browser-wallet payment; qualified e-signature; ownership/title verification; Bavarian ALKIS; strong authentication (tokens only); Indian farm-record lookups; the `npx skills add … masumi` install command was not run (the guide, quickstart and CLI-bundled skills were read directly).

## Known weaknesses found while testing
* A single Overpass outage makes a live audit slow (up to ~70 s of retries, by design) or flag a source unavailable; a failed audit execution retries 3 times then ends **undelivered** (no hash submitted).
* The geo services' dependency pins are minimums (`>=`) in their own requirements; this repo pins the tested set in the root `requirements.txt`.
* Workspaces are bearer tokens in browser storage; clearing site data loses access.

## Session 2 (Windows, 2026-10-30/31): real model + real Sokosumi Tasks, still no payments
| Check | Result |
|---|---|
| Offline suites on Windows (Node 24.22.2, Python 3.14.2) | gateway **31 passed**, Node **27 passed** (after fixing 5 Windows/consistency bugs, see HANDOFF.md section 11) |
| Real model reply (gpt-4.1-mini via OpenAI-compatible API, Eve + tools + live local gateway) | Info, order-plan (DE solar, IN wind) and lease-check (IN) briefs gave correct validated plans; an off-topic brief was declined |
| Sokosumi preprod Task `01a18f28-c334-7267-9d80-77be89c8a2f1` (Personal Workspace, Coworker AgroLand Concierge) | COMPLETED with the model answer; prices match the catalog |
| Sokosumi preprod Task `01a18f29-340b-7458-8279-b5bc967425cb` | COMPLETED with a quote (1.00 tUSDM), nothing run or charged, 0 gateway orders; follow-up comments answered |
These are execution-only checks. **No payment, registration or transaction exists yet.**
