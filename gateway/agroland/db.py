"""SQLite storage. One connection per call, WAL, foreign keys on."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL, country TEXT NOT NULL,
  persona TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), service TEXT NOT NULL, country TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'web', external_ref TEXT, idem_key TEXT,
  input TEXT NOT NULL, input_hash TEXT NOT NULL, nonce TEXT NOT NULL,
  price_amount TEXT NOT NULL, price_unit TEXT NOT NULL,
  state TEXT NOT NULL, payment TEXT NOT NULL DEFAULT '{}', result TEXT, result_hash TEXT, error TEXT,
  subject TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(user_id, idem_key));
CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS orders_state ON orders(state);
CREATE TABLE IF NOT EXISTS order_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id), at TEXT NOT NULL, event TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), filename TEXT NOT NULL, sha256 TEXT NOT NULL, kind TEXT NOT NULL,
  sample INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS parcels(
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), country TEXT NOT NULL, label TEXT NOT NULL,
  geometry TEXT NOT NULL, ref TEXT, area_ha REAL, source TEXT NOT NULL, demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS listings(
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), parcel_id TEXT NOT NULL REFERENCES parcels(id),
  audit_order_id TEXT REFERENCES orders(id), document_id TEXT REFERENCES documents(id),
  deal_type TEXT NOT NULL, price_amount REAL NOT NULL, consent INTEGER NOT NULL, consent_at TEXT,
  status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(parcel_id));
CREATE TABLE IF NOT EXISTS interests(
  id TEXT PRIMARY KEY, listing_id TEXT NOT NULL REFERENCES listings(id), developer_id TEXT NOT NULL REFERENCES users(id),
  message TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT, UNIQUE(listing_id, developer_id));
CREATE TABLE IF NOT EXISTS farm_outcomes(
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), order_id TEXT NOT NULL, finding_key TEXT NOT NULL,
  amount_per_year REAL NOT NULL, note TEXT, created_at TEXT NOT NULL, UNIQUE(user_id, order_id, finding_key));
CREATE TABLE IF NOT EXISTS farm_datasets(
  user_id TEXT PRIMARY KEY REFERENCES users(id), country TEXT NOT NULL, label TEXT NOT NULL, demo INTEGER NOT NULL,
  payload TEXT NOT NULL, sha256 TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pool_parcels(
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), country TEXT NOT NULL, label TEXT NOT NULL,
  matcher_parcel_id TEXT, project_type TEXT NOT NULL, audit TEXT, status TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pool_deals(
  match_id TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id), country TEXT NOT NULL, order_id TEXT REFERENCES orders(id),
  created_at TEXT NOT NULL, PRIMARY KEY(match_id, user_id));
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex


class Database:
    def __init__(self, state_dir: Path):
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "documents").mkdir(exist_ok=True)
        self.path = state_dir / "agroland.sqlite3"
        self.documents = state_dir / "documents"
        with self.tx() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()


def jdump(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
