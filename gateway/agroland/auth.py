"""Lightweight identities for the public demo.

There are no passwords. A visitor creates a workspace (display name + role + country) and receives a random bearer token that the
browser keeps. Every parcel, document, order, listing and deal is bound to the user id, and every query filters by it. Demo personas
(prepared parties for the two-sided pool workflow) are created the same way and are labelled `demo` in the UI.
Operators must not treat this as strong authentication: a lost token means a lost workspace.
"""
from __future__ import annotations

import hashlib
import secrets

from fastapi import Header, HTTPException

from .db import Database, new_id, now

ROLES = {"owner", "farm", "developer"}
COUNTRIES = {"DE", "IN"}


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(db: Database, name: str, role: str, country: str, persona: str | None = None) -> tuple[dict, str]:
    if role not in ROLES or country not in COUNTRIES:
        raise HTTPException(422, "role must be owner|farm|developer and country DE|IN")
    name = name.strip()
    if not 2 <= len(name) <= 80:
        raise HTTPException(422, "display name must be 2-80 characters")
    token = "agl_" + secrets.token_urlsafe(32)
    uid = new_id()
    with db.tx() as c:
        c.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?)", (uid, _h(token), name, role, country, persona, now()))
    return {"id": uid, "name": name, "role": role, "country": country, "persona": persona}, token


def user_by_token(db: Database, token: str) -> dict | None:
    with db.tx() as c:
        r = c.execute("SELECT * FROM users WHERE token_hash=?", (_h(token),)).fetchone()
    return dict(r) if r else None


def user_by_id(db: Database, uid: str) -> dict | None:
    with db.tx() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None


def make_dependency(db: Database):
    def current_user(authorization: str | None = Header(default=None)) -> dict:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Sign in first: create a workspace to get a token")
        u = user_by_token(db, authorization[7:].strip())
        if not u:
            raise HTTPException(401, "Unknown token")
        return u
    return current_user
