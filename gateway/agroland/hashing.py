"""Hashes used for orders and Masumi payments.

* report_sha256 - SHA-256 of the canonical JSON of a report. It proves that a stored report is unchanged. It does NOT prove that the
  data inside is true.
* input_hash    - MIP-004 style: sha256("<identifier_from_purchaser>;<canonical JSON of the input>").
* result hash   - what is submitted on-chain when the seller delivers. Two forms exist because two documented flows exist:
    - mip004: sha256("<identifier>;<JSON-escaped result string>") for Masumi MIP-003 jobs and web orders;
    - raw:    sha256("<identifier>;<result string>") exactly as the official TUM quickstart does for Sokosumi Coworker tasks.
"""
from __future__ import annotations

import hashlib
import json

import canonicaljson


def canonical(obj) -> str:
    return canonicaljson.encode_canonical_json(obj).decode("utf-8")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def report_sha256(report) -> str:
    return sha256_hex(canonical(report))


def input_hash(input_data, identifier: str) -> str:
    return sha256_hex(f"{identifier};{canonical(input_data)}")


def result_hash_mip004(result: str, identifier: str) -> str:
    return sha256_hex(f"{identifier};{json.dumps(result, ensure_ascii=False)[1:-1]}")


def result_hash_raw(result: str, identifier: str) -> str:
    return sha256_hex(f"{identifier};{result}")
