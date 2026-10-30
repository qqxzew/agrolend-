"""Client for the Masumi Payment Service (MPS).

Seller side (the AgroLand agents): create a payment request, observe the on-chain state, submit the result hash.
Buyer side (optional, web demo only): lock funds for a payment request with a separate buyer wallet that the operator funds.

Every write is persisted by the caller *before* it is sent; an uncertain outcome is never replayed automatically
(see orders.py). Nothing here fabricates a state: if the service is unreachable, the call raises.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from .settings import Settings

CONFIRMED_LOCKED = "FundsLocked"
DEAD_STATES = {"FundsOrDatumInvalid", "RefundRequested", "RefundAuthorized", "RefundWithdrawn", "Disputed", "DisputedWithdrawn"}
DONE_STATES = {"Withdrawn", "DisputedWithdrawn"}


class MasumiError(RuntimeError):
    pass


def iso(ms_or_dt) -> str:
    d = ms_or_dt if isinstance(ms_or_dt, datetime) else datetime.fromtimestamp(ms_or_dt / 1000, timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def confirmed(payment: dict, state: str) -> bool:
    cur = payment.get("CurrentTransaction") or {}
    if cur.get("status") == "Confirmed" and cur.get("newOnChainState") == state:
        return True
    return any(t.get("status") == "Confirmed" and t.get("newOnChainState") == state for t in payment.get("TransactionHistory") or [])


def tx_hash_for(payment: dict, state: str) -> str | None:
    for t in [payment.get("CurrentTransaction") or {}, *(payment.get("TransactionHistory") or [])]:
        if t.get("status") == "Confirmed" and t.get("newOnChainState") == state and t.get("txHash"):
            return t["txHash"]
    return None


class Mps:
    def __init__(self, base: str, token: str, network: str = "Preprod", timeout: float = 30.0):
        if not base or not token:
            raise MasumiError("payment service URL and token are not configured")
        self.base, self.token, self.network = base.rstrip("/"), token, network
        self.http = httpx.Client(timeout=timeout, follow_redirects=False)

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = self.http.post(f"{self.base}/api/v1{path}", json=body, headers={"token": self.token, "content-type": "application/json"})
        except httpx.HTTPError as exc:
            raise MasumiError(f"payment service unreachable: {type(exc).__name__}") from exc
        if r.status_code >= 400:
            raise MasumiError(f"payment service {path} -> HTTP {r.status_code}: {r.text[:240]}")
        data = r.json()
        return data.get("data", data)

    def create_payment(self, *, agent_identifier: str, source_index: int, input_hash: str, nonce: str, unit: str, amount: str,
                       windows: dict, metadata: str = "", source_type: str = "Web3CardanoV2") -> dict:
        now = datetime.now(timezone.utc)
        m = lambda k: now + timedelta(minutes=windows[k])  # noqa: E731
        return self._post("/payment", {
            "network": self.network, "agentIdentifier": agent_identifier, "paymentSourceType": source_type,
            "supportedPaymentSourceIndex": source_index, "inputHash": input_hash, "identifierFromPurchaser": nonce,
            "RequestedFunds": [{"unit": unit, "amount": amount}],
            "payByTime": iso(m("pay_by")), "submitResultTime": iso(m("submit_result")), "unlockTime": iso(m("unlock")),
            "externalDisputeUnlockTime": iso(m("external_dispute")), "metadata": metadata,
        })

    def resolve(self, blockchain_identifier: str) -> dict:
        return self._post("/payment/resolve-blockchain-identifier",
                          {"network": self.network, "blockchainIdentifier": blockchain_identifier, "includeHistory": "true"})

    def submit_result(self, blockchain_identifier: str, result_hash: str) -> dict:
        return self._post("/payment/submit-result",
                          {"network": self.network, "blockchainIdentifier": blockchain_identifier, "submitResultHash": result_hash})

    # --- buyer side --------------------------------------------------------------------------------------------------
    def purchase(self, payment: dict, *, nonce: str, source_index: int, seller_vkey: str, input_hash: str, unit: str, amount: str) -> dict:
        """Lock funds for a signed payment request. Payload mirrors the one the official quickstart sends to Sokosumi Core."""
        src = payment.get("PaymentSource") or {}
        return self._post("/purchase", {
            "blockchainIdentifier": payment["blockchainIdentifier"], "agentIdentifier": payment["agentIdentifier"], "sellerVkey": seller_vkey,
            "submitResultTime": payment["submitResultTime"], "payByTime": payment["payByTime"], "unlockTime": payment["unlockTime"],
            "externalDisputeUnlockTime": payment["externalDisputeUnlockTime"], "inputHash": input_hash, "identifierFromPurchaser": nonce,
            "paymentSourceType": "Web3CardanoV2", "supportedPaymentSourceIndex": source_index,
            "Amounts": [{"amount": amount, "unit": unit}],
            "PaymentSource": {"network": self.network, "smartContractAddress": src.get("smartContractAddress"), "policyId": src.get("policyId")},
        })


def seller_client(s: Settings) -> Mps:
    return Mps(s.mps_url, s.mps_key, s.catalog["payment"]["network"])


def buyer_client(s: Settings) -> Mps | None:
    return Mps(s.buyer_mps_url, s.buyer_mps_key, s.catalog["payment"]["network"]) if s.buyer_mps_url and s.buyer_mps_key else None


def verify_tx_on_blockfrost(tx_hash: str, key: str, address: str | None = None, unit: str | None = None) -> dict:
    """Independent check of a transaction on Cardano preprod via Blockfrost (see the query-chain skill).
    Returns what the chain says; with an address+unit it also returns the net amount that address received."""
    if not key:
        return {"verified": False, "reason": "BLOCKFROST_API_KEY_PREPROD not set"}
    h = {"project_id": key}
    base = "https://cardano-preprod.blockfrost.io/api/v0"
    try:
        tx = httpx.get(f"{base}/txs/{tx_hash}", headers=h, timeout=30)
        if tx.status_code != 200:
            return {"verified": False, "reason": f"Blockfrost HTTP {tx.status_code}"}
        out = {"verified": True, "tx_hash": tx_hash, "block": tx.json().get("block"), "block_height": tx.json().get("block_height"), "slot": tx.json().get("slot")}
        if address and unit:
            u = httpx.get(f"{base}/txs/{tx_hash}/utxos", headers=h, timeout=30).json()
            tot = lambda rows: sum(int(a["quantity"]) for r in rows if r.get("address") == address for a in r["amount"] if a["unit"] == unit)  # noqa: E731
            out["seller_net_atomic"] = str(tot(u["outputs"]) - tot(u["inputs"]))
        return out
    except httpx.HTTPError as exc:
        return {"verified": False, "reason": f"Blockfrost unreachable: {type(exc).__name__}"}
