# Qualification evidence — Cardano track

Rule (our acceptance target): at least one **completed paid job or request on Cardano preprod**, with its real **payment transaction hash**. Re-check the current rules before submitting: the track page (hackathon.tum-blockchain.com/prizes) only lists generic submission rules (video ≤ 2.5 min, Devfolio description, public repo with README); the paid-job requirement comes from the team's context notes, and the Masumi agent guide calls payment testing *optional*. We target a real paid job regardless.

**Status: PENDING — no payment, registration, Sokosumi Task or model call has been made.** Nothing below may be filled from memory, tests or mocks. The unit tests that use a fake payment service prove our state machine only; they are not evidence of a payment.

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
