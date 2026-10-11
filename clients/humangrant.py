#!/usr/bin/env python3
"""Public-interface HumanGrant client. Private keys and access tokens never enter URLs."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROTOCOL = "HumanGrant Protocol 0.1 Draft"
COMPONENTS = '("@method" "@target-uri" "content-digest" "content-type" "x-hg-key" "authorization")'
TERMINAL = {"succeeded", "rejected", "cancelled", "expired"}
REQUIRED_STATE = {
    "protocol_version", "request_id", "status", "status_text", "phase", "created_at",
    "status_updated_at", "checked_at", "expires_at", "poll_after_seconds",
    "human_authorization_url", "requested_permissions", "email_request_status",
    "email_retry_after_seconds",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def unb64u(value: str, length: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid base64url data")
    result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(result) != length or b64u(result) != value:
        raise ValueError("Noncanonical or incorrectly sized base64url data")
    return result


def compact(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def secure_json(path: Path, value: Any) -> None:
    """Create a new private file. Never replace an unrelated file or follow an existing link."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(compact(value) + b"\n")
        output.flush()
        os.fsync(output.fileno())


def read_private_json(path: Path) -> Any:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (os.name == "posix" and info.st_mode & 0o077):
        raise ValueError("Private files must be regular files with mode 0600")
    if info.st_size > 16_384:
        raise ValueError("Private file is too large")
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Identity:
    private: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> "Identity":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load(cls, path: Path) -> "Identity":
        value = read_private_json(path)
        if value.get("format") != "humangrant-key-v1":
            raise ValueError("Unknown identity format")
        identity = cls(Ed25519PrivateKey.from_private_bytes(unb64u(value["private_key"], 32)))
        if identity.public_key != value.get("public_key"):
            raise ValueError("Public and private keys do not match")
        return identity

    @property
    def public_key(self) -> str:
        raw = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return b64u(raw)

    @property
    def key_id(self) -> str:
        return "ed25519:" + b64u(hashlib.sha256(unb64u(self.public_key, 32)).digest())

    def save(self, path: Path) -> None:
        seed = self.private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        secure_json(path, {"format": "humangrant-key-v1", "private_key": b64u(seed), "public_key": self.public_key})

    def sign(self, data: bytes) -> str:
        return base64.b64encode(self.private.sign(data)).decode("ascii")


def signature_material(identity: Identity, method: str, target: str, body: bytes,
                       token: str = "anonymous", now: int | None = None,
                       nonce: str | None = None) -> tuple[dict[str, str], bytes]:
    created = int(time.time()) if now is None else now
    expires = created + 60
    nonce = nonce or b64u(secrets.token_bytes(24))
    unb64u(nonce, 24)
    if token != "anonymous":
        unb64u(token, 32)
    digest = "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode("ascii") + ":"
    authorization = "HumanGrant " + token
    params = f'{COMPONENTS};created={created};expires={expires};nonce="{nonce}";keyid="{identity.key_id}";alg="ed25519";tag="humangrant-0.1"'
    text = "\n".join([
        f'"@method": {method}', f'"@target-uri": {target}',
        f'"content-digest": {digest}', '"content-type": application/json',
        f'"x-hg-key": {identity.public_key}', f'"authorization": {authorization}',
        f'"@signature-params": {params}',
    ]).encode("utf-8")
    return {
        "Content-Type": "application/json", "Content-Digest": digest,
        "X-HG-Key": identity.public_key, "Authorization": authorization,
        "Signature-Input": "hg=" + params, "Signature": "hg=:" + identity.sign(text) + ":",
    }, text


def trusted_origin(origin: str, local: bool = False) -> str:
    origin = origin.rstrip("/")
    parsed = urllib.parse.urlsplit(origin)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError("Configure one exact trusted origin, without a path or credentials")
    if parsed.scheme != "https" and not (
        local and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("HTTPS is required; --local permits loopback HTTP only")
    return origin


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class ProtocolError(Exception):
    def __init__(self, status: int, code: str, retry: int = 0):
        self.status, self.code, self.retry = status, code, retry
        super().__init__(f"HTTP {status}: {code}; retry_after_seconds={retry}")


class Client:
    def __init__(self, origin: str, identity: Identity, *, local: bool = False, timeout: float = 10):
        self.origin = trusted_origin(origin, local)
        self.identity = identity
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method: str, path: str, payload: Any = None, *, token: str = "anonymous",
                markdown: bool = False) -> Any:
        if not re.fullmatch(r"/v1/[A-Za-z0-9_./-]+", path) or ".." in path or "//" in path:
            raise ValueError("Only a trusted relative HumanGrant API path is allowed")
        body = b"" if method == "GET" else compact({} if payload is None else payload)
        if len(body) > 16_384:
            raise ValueError("Request body exceeds the protocol size limit")
        headers, _ = signature_material(self.identity, method, self.origin + path, body, token)
        request = urllib.request.Request(self.origin + path, data=None if method == "GET" else body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read(1_048_577)
                if len(data) > 1_048_576:
                    raise ValueError("Response exceeds the client size limit")
                if markdown:
                    if response.headers.get_content_type() != "text/markdown":
                        raise ValueError("The state endpoint did not return real Markdown")
                    return data.decode("utf-8", errors="strict")
                if response.headers.get_content_type() != "application/json":
                    raise ValueError("The endpoint did not return JSON")
                return json.loads(data)
        except urllib.error.HTTPError as error:
            code, retry = "request_failed", 0
            try:
                detail = json.loads(error.read(16_384))
                raw_code = detail.get("error", "request_failed")
                if isinstance(raw_code, str) and re.fullmatch(r"[a-z_]{1,64}", raw_code):
                    code = raw_code
                retry = max(0, int(error.headers.get("Retry-After", detail.get("retry_after_seconds", 0))))
            except (ValueError, TypeError, AttributeError):
                pass
            raise ProtocolError(error.code, code, retry) from None

    def state(self, request_id: str) -> dict[str, Any]:
        safe_id(request_id)
        return parse_markdown(self.request("GET", f"/v1/requests/{request_id}/status.md", markdown=True))


def safe_id(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError("Invalid identifier")
    return value


def parse_markdown(text: str) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([a-z_]+): (.+)", line)
        if match:
            key, value = match.groups()
            if key in state:
                raise ValueError("Duplicate state field")
            state[key] = json.loads(value)
    if not REQUIRED_STATE.issubset(state) or state["protocol_version"] != PROTOCOL:
        raise ValueError("Unsupported or incomplete state representation")
    if state["phase"] not in TERMINAL | {"waiting_human", "authenticating_human", "awaiting_consent", "approved"}:
        raise ValueError("Unknown phase")
    for field in ("created_at", "status_updated_at", "checked_at", "expires_at", "poll_after_seconds", "email_retry_after_seconds"):
        if type(state[field]) is not int or state[field] < 0:
            raise ValueError("Invalid state time")
    return state


def next_delay(previous: int, server: int = 0, *, network_error: bool = False) -> int:
    if min(previous, server) < 0:
        raise ValueError("Negative polling interval")
    if network_error:
        return max(server, min(60, max(previous, 1) * 2))
    return max(previous, server, 1)


def watch(client: Client, initial: dict[str, Any], *, sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], float] = time.time, on_state: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Read Markdown again; do not execute page instructions or silently create another request."""
    state, failures = initial, 0
    interval = max(1, int(initial["poll_after_seconds"]))
    # Use server time plus elapsed client time, rather than assuming synchronized wall clocks.
    local_start, server_start = clock(), int(initial["checked_at"])
    expires = int(initial["expires_at"])
    while state["phase"] not in TERMINAL and state["phase"] != "approved":
        remaining = expires - (server_start + clock() - local_start)
        if remaining <= 0:
            raise TimeoutError("The known request deadline was reached; no new request was created")
        sleep(min(interval, remaining))
        if server_start + clock() - local_start >= expires:
            raise TimeoutError("The known request deadline was reached; no new request was created")
        try:
            state = client.state(initial["request_id"])
            failures = 0
            interval = next_delay(interval, int(state["poll_after_seconds"]))
            if on_state:
                on_state(state)
        except ProtocolError as error:
            if error.status == 429:
                interval = next_delay(interval, max(error.retry, interval + 5))
            elif error.status >= 500:
                failures += 1
                interval = next_delay(interval, error.retry, network_error=True)
            else:
                raise
        except (OSError, urllib.error.URLError):
            failures += 1
            interval = next_delay(interval, network_error=True)
        if failures >= 6:
            raise TimeoutError("Six consecutive failures; polling stopped without a new request")
    return state


def save_claim(client: Client, request_id: str, path: Path) -> dict[str, Any]:
    if path.exists() or path.is_symlink():
        raise FileExistsError("Refusing to replace the session output file")
    result = client.request("POST", f"/v1/requests/{safe_id(request_id)}/claim")
    unb64u(result["access_token"], 32)
    result.update({"origin": client.origin, "actor_id": client.identity.key_id, "request_id": request_id})
    try:
        secure_json(path, result)
    except OSError as error:
        raise RuntimeError("The credential was issued but could not be saved. Revoke this grant before requesting new access.") from error
    return {"grant_id": result["grant_id"], "expires_at": result["expires_at"], "session_file": str(path)}


def load_session(client: Client, path: Path) -> str:
    session = read_private_json(path)
    if session.get("origin") != client.origin or session.get("actor_id") != client.identity.key_id:
        raise ValueError("The saved session belongs to another origin or identity")
    if session.get("expires_at", 0) <= time.time():
        raise ValueError("The saved session has expired")
    unb64u(session["access_token"], 32)
    return session["access_token"]


def sign_challenge(identity: Identity, origin: str, challenge: str, now: int | None = None) -> dict[str, str]:
    value = json.loads(challenge)
    now = int(time.time()) if now is None else now
    if not isinstance(value, list) or len(value) != 6 or value[0] != "HumanGrant human authentication 0.1" or value[1] != origin:
        raise ValueError("Refusing to sign a challenge for another purpose or origin")
    for field in value[2:5]:
        safe_id(field)
    if type(value[5]) is not int or not now < value[5] <= now + 150:
        raise ValueError("Human authentication challenge is expired or too long-lived")
    if compact(value).decode("utf-8") != challenge:
        raise ValueError("The challenge is not canonical UTF-8 JSON")
    return {"public_key": identity.public_key, "signature": identity.sign(challenge.encode("utf-8"))}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=PROTOCOL)
    parser.add_argument("--origin", default="http://127.0.0.1:8787")
    parser.add_argument("--local", action="store_true", help="Allow loopback HTTP only")
    parser.add_argument("--key", type=Path, help="Local private identity file; never uploaded")
    sub = parser.add_subparsers(dest="command", required=True)
    keygen = sub.add_parser("keygen", help="Create a new local Ed25519 identity")
    keygen.add_argument("--out", type=Path, required=True)
    sub.add_parser("public", help="Show the public identity only")
    create = sub.add_parser("request", help="Create one authorization request")
    create.add_argument("--client-id", default="example-cli")
    create.add_argument("--service", default="notes")
    create.add_argument("--purpose", required=True)
    create.add_argument("--permissions", nargs="+", required=True, metavar="ACTION:RESOURCE")
    create.add_argument("--expected-human")
    create.add_argument("--watch", action="store_true")
    create.add_argument("--session-out", type=Path)
    status = sub.add_parser("status", help="Read real Markdown; optionally poll")
    status.add_argument("request_id")
    status.add_argument("--watch", action="store_true")
    status.add_argument("--session-out", type=Path)
    invite = sub.add_parser("email", help="Invite only an email address the user has allowed you to contact")
    invite.add_argument("request_id")
    invite.add_argument("--email", required=True)
    invite.add_argument("--operation", required=True, help="Reuse this key only for an identical retry")
    claim = sub.add_parser("claim", help="Claim once and save a separate restricted session")
    claim.add_argument("request_id")
    claim.add_argument("--out", required=True, type=Path)
    cancel = sub.add_parser("cancel")
    cancel.add_argument("request_id")
    session = sub.add_parser("session")
    session.add_argument("--session", required=True, type=Path)
    for name in ("read", "write"):
        note = sub.add_parser(name)
        note.add_argument("resource")
        note.add_argument("--session", type=Path, help="Omit only when using a registered human identity")
        if name == "write":
            note.add_argument("--content", required=True)
    sub.add_parser("grants", help="List grants using the registered human identity")
    revoke = sub.add_parser("revoke")
    revoke.add_argument("grant_id")
    sign = sub.add_parser("sign-challenge", help="Human-only local alternative to browser signing")
    sign.add_argument("--challenge-file", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "keygen":
        identity = Identity.generate()
        identity.save(args.out)
        print(json.dumps({"public_key": identity.public_key, "key_id": identity.key_id, "identity_file": str(args.out)}))
        return 0
    if args.key is None:
        raise ValueError("--key is required for this command")
    identity = Identity.load(args.key)
    if args.command == "public":
        print(json.dumps({"public_key": identity.public_key, "key_id": identity.key_id}))
        return 0
    client = Client(args.origin, identity, local=args.local)
    if args.command == "sign-challenge":
        raw = args.challenge_file.read_text(encoding="utf-8").strip()
        parsed = json.loads(raw)
        challenge = parsed["challenge"] if isinstance(parsed, dict) else raw
        result: Any = sign_challenge(identity, client.origin, challenge)
    elif args.command == "request":
        if args.watch and args.session_out is None:
            raise ValueError("--watch requires --session-out so a credential is not printed")
        permissions = []
        for permission in args.permissions:
            action, resource = permission.split(":", 1)
            safe_id(resource)
            if action not in {"notes.read", "notes.write"}:
                raise ValueError("Unknown permission")
            permissions.append({"action": action, "resource": resource})
        payload = {"client_id": args.client_id, "target_service": args.service,
                   "purpose": args.purpose, "requested_permissions": permissions,
                   "expected_human_id": args.expected_human}
        result = client.request("POST", "/v1/requests", payload)
    elif args.command == "status":
        if args.watch and args.session_out is None:
            raise ValueError("--watch requires --session-out")
        raw = client.request("GET", f"/v1/requests/{safe_id(args.request_id)}/status.md", markdown=True)
        result = parse_markdown(raw)
    elif args.command == "email":
        result = client.request("POST", f"/v1/requests/{safe_id(args.request_id)}/email", {"email": args.email, "idempotency_key": safe_id(args.operation)})
    elif args.command == "claim":
        result = save_claim(client, args.request_id, args.out)
    elif args.command == "cancel":
        result = client.request("POST", f"/v1/requests/{safe_id(args.request_id)}/cancel")
    elif args.command == "session":
        result = client.request("GET", "/v1/session", token=load_session(client, args.session))
    elif args.command in {"read", "write"}:
        token = load_session(client, args.session) if args.session else "anonymous"
        result = client.request("GET" if args.command == "read" else "PUT", "/v1/notes/" + safe_id(args.resource),
                                None if args.command == "read" else {"content": args.content}, token=token)
    elif args.command == "grants":
        result = client.request("GET", "/v1/human/grants")
    elif args.command == "revoke":
        result = client.request("POST", f"/v1/human/grants/{safe_id(args.grant_id)}/revoke")
    else:
        raise ValueError("Unknown command")
    if args.command in {"request", "status"}:
        # Creation returns Location + JSON, then the CLI reads the actual Markdown endpoint.
        if args.command == "request":
            time.sleep(max(0, int(result["poll_after_seconds"])))
            raw = client.request("GET", f"/v1/requests/{safe_id(result['request_id'])}/status.md", markdown=True)
            result = parse_markdown(raw)
        print(raw)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if getattr(args, "watch", False):
        if "human_authorization_url" in result:
            print("Forward this human-only review link: " + result["human_authorization_url"], file=sys.stderr)
        state = watch(client, result, on_state=lambda value: print(json.dumps({"phase": value["phase"], "checked_at": value["checked_at"]})))
        if state["phase"] == "approved":
            print(json.dumps(save_claim(client, state["request_id"], args.session_out)))
        elif state["phase"] == "succeeded":
            raise RuntimeError("A credential was already issued. This command did not receive it; use the original saved session or revoke the grant.")
        else:
            print(json.dumps({"phase": state["phase"], "polling_stopped": True}))
            return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, ProtocolError, RuntimeError, KeyError) as failure:
        print(str(failure), file=sys.stderr)
        raise SystemExit(1) from None
