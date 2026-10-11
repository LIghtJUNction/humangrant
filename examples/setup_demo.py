#!/usr/bin/env python3
"""Generate local identities and a loopback-only configuration. Never send email."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "clients"))
from humangrant import Identity, secure_json  # noqa: E402


def setup(destination: Path, port: int = 8787) -> Path:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Refusing to overwrite a nonempty demo directory")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    identities = {name: Identity.generate() for name in ("ai", "alice", "bob")}
    for name, identity in identities.items():
        identity.save(destination / f"{name}.key.json")
    config = {
        "public_origin": f"http://127.0.0.1:{port}", "listen": f"127.0.0.1:{port}",
        "database": str(destination / "humangrant.db"), "local_development": True,
        "client_ids": ["example-cli", "example-browser"],
        "accounts": [{"id": name, "public_key": identities[name].public_key} for name in ("alice", "bob")],
        "resources": [
            {"id": "alice-note", "owner_id": "alice", "content": "Alice's private note.", "permissions": ["notes.read", "notes.write"]},
            {"id": "alice-other-note", "owner_id": "alice", "content": "Not included in the request.", "permissions": ["notes.read", "notes.write"]},
            {"id": "bob-note", "owner_id": "bob", "content": "Bob's private note.", "permissions": ["notes.read", "notes.write"]},
        ],
        "mail": {"mode": "local", "spool": str(destination / "outbox")},
    }
    secure_json(destination / "config.json", config)
    return destination / "config.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=Path(".state"))
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535")
    try:
        print(json.dumps({"config": str(setup(args.dir, args.port)), "mail": "local-only; no real mail sent"}))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
