# Qualification evidence — Cardano track

Rule (our acceptance target): at least one **completed paid job or request on Cardano preprod**, with its real **payment transaction hash**. Re-check the current rules before submitting: the track page (hackathon.tum-blockchain.com/prizes) only lists generic submission rules (video ≤ 2.5 min, Devfolio description, public repo with README); the paid-job requirement comes from the team's context notes, and the Masumi agent guide calls payment testing *optional*. We target a real paid job regardless.

**Status: ORDER-LINKED PAID JOB VERIFIED — see the next section (checked on the production server and Blockfrost, 31 Oct 2026).** The remaining PENDING cells below are only what has no source record yet. Nothing below may be filled from memory, tests or mocks. The unit tests that use a fake payment service prove our state machine only; they are not evidence of a payment.

## Observed on-chain (preprod, 31 Oct 2026 UTC) — Blockfrost
Data: `docs/evidence/onchain-seller-receipts.json`. Seller `addr_test1qqymrsxu2yhfpc9e2vqwcfwadgv2cnfunrh7g3kuuuqtskazy9lfldexrs2hd0y2ga363dqksg84mlhffnxxw4u043qqcrg536` now holds ≈991.43 tADA and **11 tUSDM** (policy `16a55b2a…`, the unit in `config/services.json`).

- **Buyer lock (`PaymentBatched`)**, funded by a separate buyer address `addr_test1qz2aac04ekm83yyy6d0wwah870939s52a3d704saq7fqagm606t6gx6v3cg7sy9g652dvg2v5qf3mdmz0d9vl77shr6s0h5dsg`: `69f54064e43f4e970cd7325a97cfe9ce28b7c7b3018cd8c1a47bb49a6c2366ed` (00:45 UTC) and `0563bd77aa9f07e482eb9070c63c99a9e262eee1f1f7b5bb68537859171ae671` (01:04 UTC).
- **Seller result submission (`SubmitResult`)**, spends the escrow UTxOs: `be9ff838…`, `0740166e…`, `7f23e1e0…`, `b8f0aa60…`, `c008ca59…`, `e1ba5b39…` (00:46–01:10 UTC). Full hashes in the JSON.
- **Seller collection (`CollectCompleted`)**, escrow to seller: `4147608f672f8fe6c9b1b4cf83d0176b5ec8efb22e9b31a9573487085f5a507b` (1 tUSDM), `ca27bce104f01b778707f408e2676747fa955d0e7d98ee8e3f4c53dc98675307` (9 tUSDM, 7 payments), `763bb816e288910673ba6f585baa70552fdafde851346e0489ac7b3151c5713e` (1 tUSDM).
- **Sokosumi Task "TEST A4"** (wind audit 23.35, 70.55, IN): Completed, comment "Payment requested: 1.00 tUSDM", report SHA-256 `8b6cc46ad94659e4071d0251c057799ace0b1e5efa2062bda1ff980b5dee066a`. Task state `agent/.local/01a18f7a-6fd7-771a-8fe5-d3dba9fe15b3.json`, order `e4ed53a09e4043629bd4a3b2f08d93bb`, stage `awaiting-withdrawal` when last saved. Two more Tasks completed the same way (orders `22a4eb55…`, `dda6a89f…`).

## Verified paid job, linked order → Task → transactions (production server, 31 Oct 2026)
Read from the production gateway database (`/data/gateway/agroland.sqlite3`, read-only) on the Hack Club server and re-checked against Blockfrost preprod.

| Item | Value |
|---|---|
| Service, price | Land Audit, **1.00 tUSDM** (country DE, solar, point 52.0746, 12.7329, r=300 m) |
| Sokosumi Task (Coworker AgroLand Concierge, Personal Workspace) | `01a19166-d167-745b-beaa-b58383cedb5d` — phase `completed` |
| Gateway order | `4f650b3982984020a777a72e250c8717` — state `delivered`, payment stage `settled`, on-chain state `Withdrawn` |
| Result hash (SHA-256 of the delivered Markdown, submitted on-chain) | `e773187dab2a7d0b9041c6e71978ac7c9bcf54575f6c5a6e3295d7da04a87694` |
| **Funds-locked tx** | `6087b1ff78b9fda9b8bab5da84fde83d5194acf96a1ff6f2de9548865c0aa10d` — block 5356666, 2026-10-31 10:03 UTC |
| **Result-hash tx** | `60ce47ffaa92116a1d45cc6d5ec0109c659cc045cde28aa1971d90851920988c` — block 5356670, 10:04 UTC |
| **Seller settlement tx** | `607ee2d0f82628ad2162b1b514ab0fb47ceef4eb300905e257b7cb0ce394acc4` — block 5356860, 11:15 UTC |
| Explorer | https://preprod.cardanoscan.io/transaction/6087b1ff78b9fda9b8bab5da84fde83d5194acf96a1ff6f2de9548865c0aa10d |
| Registered agents | all three `RegistrationConfirmed`, policy `67ab0c92c4ac…`, `apiBaseUrl` `https://audit.mrrobot.hackclub.app/masumi/<service>`; `/availability` answers `available` for each |

Earlier Sokosumi Tasks (night of 30→31 Oct) are also `delivered` and `settled`: land_audit ×7 (DE ×4, IN ×3), lease_check ×2 (DE, IN). Their lock / result / settlement transactions are in the gateway database (several orders share one batched lock and one collection). Two early orders ended `failed` ("Payment request outcome unknown; inspect before retrying") and two web/Sokosumi orders `expired` unpaid; they were not retried automatically, as designed.


**Earlier note (superseded by the section above):** which lock / result / collect transaction belongs to which order. The local dev gateway database does not hold these orders; the worker uses the production gateway (`AGROLAND_URL`). Run `python scripts/evidence.py --state <production state dir>` there, and `runtime receipt` for each Task. A first version of this section wrongly called the `SubmitResult` transactions "locks" and the payment a self-payment; the trace above (buyer-funded `PaymentBatched` transactions) corrects that.

| Item | Value | Source of truth |
|---|---|---|
| Model reply check (Task id + reply) | `01a18f28-c334-7267-9d80-77be89c8a2f1` COMPLETED (see docs/VERIFICATION.md) | `agent/.local/<TASK_ID>-session.json`, Sokosumi Task events |
| Execution-only Coworker Task id | `01a18f29-340b-7458-8279-b5bc967425cb` COMPLETED, quote only (docs/VERIFICATION.md) | `sokosumi --preprod tasks get <ID> --json` |
| Paid Task id / MIP-003 job id | `01a19166-d167-745b-beaa-b58383cedb5d` / order `4f650b39…` (section above) | Sokosumi / `GET /api/orders/{id}` |
| Service, price | Land Audit 1.00 tUSDM for the verified job (catalog: Land Audit 1.00 tUSDM, Lease Check 2.00, Pool Access 3.00) | `config/services.json` |
| Result (report text) + report SHA-256 | hash `e773187d…7694` recorded; report text via | `GET /api/orders/{id}/result` |
| Result hash submitted on-chain | `e773187d…7694` | order `result_hash`; payment service state |
| **Funds-locked tx hash** | `6087b1ff…aa10d` (section above) | `python scripts/evidence.py` |
| Result-hash tx hash | `60ce47ff…0988c` | same |
| **Seller settlement tx hash** | `607ee2d0…acc4` | same + Sokosumi receipt (`runtime receipt`) |
| Seller **net receipt** verified (Blockfrost) | PENDING | `agent/.local/evidence/<TASK_ID>.json` |
| Explorer links | https://preprod.cardanoscan.io/transaction/6087b1ff78b9fda9b8bab5da84fde83d5194acf96a1ff6f2de9548865c0aa10d (and the other two hashes) | cardanoscan preprod |
| Registered agent identifiers (3) | all `RegistrationConfirmed` on the server | `agent/docs/registration-state.json` |

## Commands to produce the evidence (after authorization — see DEPLOY.md B6)
```bash
python scripts/evidence.py --write docs/evidence/orders.json     # real orders with observed chain transactions
cat agent/.local/evidence/<TASK_ID>.json                         # Core receipt + Blockfrost net receipt for a Coworker Task
curl -s -H "Authorization: Bearer <workspace token>" https://<domain>/api/orders/<ORDER_ID>/verify   # hash + chain checks
```
A hash confirms that a stored report is unchanged. It does not prove the data in it is true. A correct negative report (e.g. NO_GO) is a completed paid service.
