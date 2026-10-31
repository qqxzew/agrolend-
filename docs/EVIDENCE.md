# Qualification evidence — Cardano track

Rule (our acceptance target): at least one **completed paid job or request on Cardano preprod**, with its real **payment transaction hash**. Re-check the current rules before submitting: the track page (hackathon.tum-blockchain.com/prizes) only lists generic submission rules (video ≤ 2.5 min, Devfolio description, public repo with README); the paid-job requirement comes from the team's context notes, and the Masumi agent guide calls payment testing *optional*. We target a real paid job regardless.

**Status: PARTIAL — real paid Sokosumi Tasks ran and the seller received payment on preprod; the evidence table below still needs its per-Task hashes filled from the Task files and the production gateway.** Nothing below may be filled from memory, tests or mocks. The unit tests that use a fake payment service prove our state machine only; they are not evidence of a payment.

## Observed on-chain (preprod, 31 Oct 2026 UTC) — Blockfrost
Data: `docs/evidence/onchain-seller-receipts.json`. Seller `addr_test1qqymrsxu2yhfpc9e2vqwcfwadgv2cnfunrh7g3kuuuqtskazy9lfldexrs2hd0y2ga363dqksg84mlhffnxxw4u043qqcrg536` now holds ≈991.43 tADA and **11 tUSDM** (policy `16a55b2a…`, the unit in `config/services.json`).

- **Buyer lock (`PaymentBatched`)**, funded by a separate buyer address `addr_test1qz2aac04ekm83yyy6d0wwah870939s52a3d704saq7fqagm606t6gx6v3cg7sy9g652dvg2v5qf3mdmz0d9vl77shr6s0h5dsg`: `69f54064e43f4e970cd7325a97cfe9ce28b7c7b3018cd8c1a47bb49a6c2366ed` (00:45 UTC) and `0563bd77aa9f07e482eb9070c63c99a9e262eee1f1f7b5bb68537859171ae671` (01:04 UTC).
- **Seller result submission (`SubmitResult`)**, spends the escrow UTxOs: `be9ff838…`, `0740166e…`, `7f23e1e0…`, `b8f0aa60…`, `c008ca59…`, `e1ba5b39…` (00:46–01:10 UTC). Full hashes in the JSON.
- **Seller collection (`CollectCompleted`)**, escrow to seller: `4147608f672f8fe6c9b1b4cf83d0176b5ec8efb22e9b31a9573487085f5a507b` (1 tUSDM), `ca27bce104f01b778707f408e2676747fa955d0e7d98ee8e3f4c53dc98675307` (9 tUSDM, 7 payments), `763bb816e288910673ba6f585baa70552fdafde851346e0489ac7b3151c5713e` (1 tUSDM).
- **Sokosumi Task "TEST A4"** (wind audit 23.35, 70.55, IN): Completed, comment "Payment requested: 1.00 tUSDM", report SHA-256 `8b6cc46ad94659e4071d0251c057799ace0b1e5efa2062bda1ff980b5dee066a`. Task state `agent/.local/01a18f7a-6fd7-771a-8fe5-d3dba9fe15b3.json`, order `e4ed53a09e4043629bd4a3b2f08d93bb`, stage `awaiting-withdrawal` when last saved. Two more Tasks completed the same way (orders `22a4eb55…`, `dda6a89f…`).

**Still to link:** which lock / result / collect transaction belongs to which order. The local dev gateway database does not hold these orders; the worker uses the production gateway (`AGROLAND_URL`). Run `python scripts/evidence.py --state <production state dir>` there, and `runtime receipt` for each Task. A first version of this section wrongly called the `SubmitResult` transactions "locks" and the payment a self-payment; the trace above (buyer-funded `PaymentBatched` transactions) corrects that.

| Item | Value | Source of truth |
|---|---|---|
| Model reply check (Task id + reply) | PENDING | `agent/.local/<TASK_ID>-session.json`, Sokosumi Task events |
| Execution-only Coworker Task id | PENDING | `sokosumi --preprod tasks get <ID> --json` |
| Paid Task id / MIP-003 job id | PENDING | Sokosumi / `GET /api/orders/{id}` |
| Service, price | PENDING (catalog: Land Audit 1.00 tUSDM, Lease Check 2.00, Pool Access 3.00) | `config/services.json` |
| Result (report text) + report SHA-256 | PENDING | `GET /api/orders/{id}/result` |
| Result hash submitted on-chain | PENDING | order `result_hash`; payment service state |
| **Funds-locked tx hash** | PENDING | `python scripts/evidence.py` |
| Result-hash tx hash | PENDING | same |
| **Seller settlement tx hash** | PENDING | same + Sokosumi receipt (`runtime receipt`) |
| Seller **net receipt** verified (Blockfrost) | PENDING | `agent/.local/evidence/<TASK_ID>.json` |
| Explorer links | PENDING | https://preprod.cardanoscan.io/transaction/<hash> |
| Registered agent identifiers (3) | PENDING | `agent/docs/registration-state.json` |

## Commands to produce the evidence (after authorization — see DEPLOY.md B6)
```bash
python scripts/evidence.py --write docs/evidence/orders.json     # real orders with observed chain transactions
cat agent/.local/evidence/<TASK_ID>.json                         # Core receipt + Blockfrost net receipt for a Coworker Task
curl -s -H "Authorization: Bearer <workspace token>" https://<domain>/api/orders/<ORDER_ID>/verify   # hash + chain checks
```
A hash confirms that a stored report is unchanged. It does not prove the data in it is true. A correct negative report (e.g. NO_GO) is a completed paid service.
