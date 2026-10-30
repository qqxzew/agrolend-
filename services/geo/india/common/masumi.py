"""Masumi helpers shared by the India agents: MIP-004 hashing and the payment-service client (Cardano Preprod, V2).

Same wire behaviour as the German agents (`app/masumi.py`); kept as a separate copy so the two stacks stay independent.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

import canonicaljson
import httpx

PAID_STATES = {"FundsLocked", "ResultSubmitted", "WithdrawAuthorized", "Withdrawn"}
DEAD_STATES = {"FundsOrDatumInvalid", "RefundRequested", "RefundAuthorized", "RefundWithdrawn", "Disputed", "DisputedWithdrawn"}


def _hash_payload(payload: str, identifier_from_purchaser: str) -> str:
    return hashlib.sha256(f"{identifier_from_purchaser};{payload}".encode("utf-8")).hexdigest()


def input_hash(input_data: dict[str, Any], identifier_from_purchaser: str) -> str:
    """MIP-004: sha256("<identifier>;<JCS(input)>")."""
    return _hash_payload(canonicaljson.encode_canonical_json(input_data).decode("utf-8"), identifier_from_purchaser)


def output_hash(result: str, identifier_from_purchaser: str) -> str:
    """MIP-004: sha256("<identifier>;<json-escaped result string>") — what the buyer verifies on-chain."""
    return _hash_payload(json.dumps(result, ensure_ascii=False)[1:-1], identifier_from_purchaser)


def unix(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return v
    return v


class PaymentSettings(Protocol):
    masumi_payment_service_url: str
    masumi_api_key: str
    masumi_network: str
    masumi_payment_source_type: str
    masumi_supported_payment_source_index: str
    masumi_requested_funds_lovelace: str


class PaymentClient:
    """Client of the Masumi payment service. `agent_identifier` is the registry id of the agent that sells the service."""

    def __init__(self, client: httpx.AsyncClient, s: PaymentSettings, agent_identifier: str):
        self.http, self.s, self.agent_identifier = client, s, agent_identifier
        self.base = s.masumi_payment_service_url.rstrip("/") + "/api/v1/payment"
        self.headers = {"token": s.masumi_api_key, "Content-Type": "application/json"}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self.http.post(f"{self.base}{path}", json=payload, headers=self.headers, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"payment service {path or '/'} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    async def create(self, identifier: str, in_hash: str, metadata: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"  # noqa: E731
        payload: dict[str, Any] = {
            "agentIdentifier": self.agent_identifier,
            "network": self.s.masumi_network,
            "paymentType": "Web3CardanoV1",
            "payByTime": fmt(now + timedelta(hours=12)),
            "submitResultTime": fmt(now + timedelta(hours=24)),
            "identifierFromPurchaser": identifier,
            "inputHash": in_hash,
            "metadata": metadata,
        }
        if self.s.masumi_payment_source_type:  # payment-service 0.29 seeds only Web3CardanoV2
            payload["paymentSourceType"] = self.s.masumi_payment_source_type
            payload.pop("paymentType")
        if self.s.masumi_supported_payment_source_index:
            payload["supportedPaymentSourceIndex"] = int(self.s.masumi_supported_payment_source_index)
        if self.s.masumi_requested_funds_lovelace:
            payload["RequestedFunds"] = [{"amount": self.s.masumi_requested_funds_lovelace, "unit": ""}]
        return (await self._post("/", payload))["data"]

    async def state(self, blockchain_identifier: str) -> Optional[str]:
        body = await self._post(
            "/resolve-blockchain-identifier",
            {"network": self.s.masumi_network, "blockchainIdentifier": blockchain_identifier, "includeHistory": "false"},
        )
        return (body.get("data") or {}).get("onChainState")

    async def submit_result(self, blockchain_identifier: str, result_hash: str) -> None:
        await self._post(
            "/submit-result",
            {"network": self.s.masumi_network, "blockchainIdentifier": blockchain_identifier, "submitResultHash": result_hash},
        )


class MasumiConfig:
    """Concrete `PaymentSettings` for services that only need the payment-service connection."""

    def __init__(self, url: str, api_key: str, network: str = "Preprod", source_type: str = "",
                 source_index: str = "", requested_funds_lovelace: str = ""):
        self.masumi_payment_service_url = url
        self.masumi_api_key = api_key
        self.masumi_network = network
        self.masumi_payment_source_type = source_type
        self.masumi_supported_payment_source_index = source_index
        self.masumi_requested_funds_lovelace = requested_funds_lovelace
