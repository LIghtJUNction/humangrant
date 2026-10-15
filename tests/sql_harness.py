"""Exercise the actual shipped SQL, NOT a substitute Python implementation of the Rust HTTP server."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from humangrant import b64u

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self, now: int = 1_700_000_000):
        self.now = now
    def advance(self, seconds: int = 1) -> None:
        self.now += seconds


def connect(path: Path, clock: Clock) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.create_function("hg_now", 0, lambda: clock.now)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def sql(db: sqlite3.Connection, name: str, values: dict[str, Any] | None = None):
    return db.execute((ROOT / "src/sql" / (name + ".sql")).read_text(), values or {})


def initialize(db: sqlite3.Connection, *, existing_login: bool = True) -> None:
    db.executescript((ROOT / "migrations/0001.sql").read_text())
    if existing_login:
        db.executescript((ROOT / "migrations/0002_existing_login.sql").read_text())
    for account in ("alice", "bob"):
        db.execute("INSERT INTO accounts(id,key_id,public_key) VALUES(?,?,?)", (account, "human:" + account, "public:" + account))
    db.execute("INSERT INTO clients VALUES('example-cli','notes')")
    for action in ("notes.read", "notes.write"):
        db.execute("INSERT INTO service_policy VALUES('notes',?)", (action,))
    for resource, owner in (("alice-note", "alice"), ("alice-other-note", "alice"), ("bob-note", "bob")):
        db.execute("INSERT INTO resources VALUES('notes',?,?,?)", (resource, owner, owner + " secret"))
        for action in ("notes.read", "notes.write"):
            db.execute("INSERT INTO entitlements VALUES(?,'notes',?,?)", (owner, action, resource))


def create(db: sqlite3.Connection, clock: Clock, request_id: str = "r1", actor: str = "agent-A",
           permissions: list[dict[str, str]] | None = None, expected: str | None = None) -> str:
    permissions = permissions if permissions is not None else [
        {"action": "notes.read", "resource": "alice-note"}, {"action": "notes.write", "resource": "alice-note"}]
    sql(db, "create_request", {
        "id": request_id, "actor": actor, "public_key": actor + "-public", "client": "example-cli",
        "service": "notes", "purpose": "Read a note", "permissions": json.dumps(permissions),
        "expected": expected, "link": "link-" + request_id, "expires": clock.now + 600,
        "grant_expires": clock.now + 3600, "poll_interval": 5, "audit": "audit-" + request_id,
    })
    return request_id


def consent_phase(db: sqlite3.Connection, request_id: str = "r1") -> None:
    # SQL invariant tests only: authentication itself is tested by the separate Rust/HTTP tests.
    for phase in ("authenticating_human", "awaiting_consent"):
        db.execute("UPDATE requests SET phase=?,status_updated_at=hg_now() WHERE id=?", (phase, request_id))


def approve(db: sqlite3.Connection, clock: Clock, request_id: str = "r1", human: str = "alice",
            permissions: list[dict[str, str]] | None = None, expires: int | None = None) -> str:
    grant = "grant-" + request_id
    sql(db, "approve", {"id": grant, "request": request_id, "human": human,
        "permissions": json.dumps(permissions if permissions is not None else [{"action": "notes.read", "resource": "alice-note"}]),
        "expires": expires or clock.now + 1800})
    return grant


def claim(db: sqlite3.Connection, request_id: str = "r1", actor: str = "agent-A", token: str = "restricted-test-token") -> int:
    return sql(db, "claim", {"id": "session-" + request_id, "request": request_id, "actor": actor,
        "token_hash": b64u(hashlib.sha256(token.encode()).digest())}).rowcount


def effective(db: sqlite3.Connection, actor: str = "agent-A", token: str = "restricted-test-token", service: str = "notes") -> set[tuple[str, str]]:
    rows = sql(db, "effective_permissions", {"actor": actor,
        "token_hash": b64u(hashlib.sha256(token.encode()).digest()), "service": service})
    return {(row["action"], row["resource"]) for row in rows}


def mail_allowed(db: sqlite3.Connection, *, recipient: str = "mail-hash", actor: str = "agent-A", source: str = "source-hash", **limits: int) -> bool:
    values = {"recipient_hash": recipient, "actor": actor, "source": source,
        "cooldown": 60, "recipient_hour": 3, "recipient_day": 5, "actor_hour": 10,
        "source_hour": 10, "service_hour": 100, "service_day": 500}
    values.update(limits)
    return bool(sql(db, "mail_allow", values).fetchone()[0])


def enqueue(db: sqlite3.Connection, request_id: str = "r1", operation: str = "op1", *,
            actor: str = "agent-A", recipient: str = "mail-hash", source: str = "source-hash", state: str = "queued", key: str | None = None) -> None:
    sql(db, "mail_enqueue", {"id": operation, "request": request_id, "actor": actor,
        "key": key or operation, "recipient_hash": recipient, "source": source,
        "recipient": "recipient@example.test" if state != "suppressed" else None,
        "state": state, "action_token": "action-" + operation, "subject": "HumanGrant permission request", "body": "Fixed local test content"})
