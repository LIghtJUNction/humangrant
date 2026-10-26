# Integrate an existing project

Protocol: **HumanGrant Protocol 0.1 Draft**. Public contracts are [OpenAPI](../openapi.yaml),
[field schemas](../schemas/protocol.json), [signature vector](../tests/fixtures/signature.json), and
[the protocol](../spec/v0.1.md). The [integration skill](../skills/humangrant-integrate/SKILL.md)
is an operational checklist, not a replacement for reading the target's code.

## Choose a narrow boundary

Inspect the target's real login verification, account IDs, authorization checks, database transactions,
UI and deployment. Keep its human login and account model. Implement the protocol in the existing
backend, or use a trusted host-side adapter. Do not introduce a third-party account to satisfy this
draft. Do not proxy arbitrary business access through the notes demo and call it a general integration.
The standalone reference has a fixed `notes` policy; host-specific adapters are not delivered here.

The exposed Rust library entrypoints are `App::new`, `App::with_authenticator`, `HttpInput`, and
`HttpOutput`. [src/auth.rs](../src/auth.rs) defines `HumanAuthenticator::authenticate` and `HumanPrincipal`.
The default implementation verifies the exact human challenge using an operator-provisioned public
key and checks the enabled local account. An adapter must remain trusted server code. It must verify
real, short-lived host evidence and map to a stable account; returning any caller's `user_id` is not an
adapter. It must remain bound to the challenge, browser/request and CSRF-protected consent context.
For an existing browser login, override `HumanAuthenticator::session_principal(db, cookie, now)`.
It is called on review, consent, grant listing and revocation. Validate the host's actual session,
expiry, logout and current account, then return its principal; return `None` for no valid login.
The override is authoritative and does not fall back to a reference cookie. The account must be
mapped to the host's current permission records. Do not copy a host identity into a long-lived
reference session. The default implementation checks the reference's public-key-verified login.

The HTTP schemas contain public-key/signature evidence for the reference proof. A different host login
mechanism needs its own documented host-bound verification endpoint or a fully specified proof adapter;
do not silently rename a cookie to a signature and claim wire compatibility. The public agent-facing
request/state/claim/session API can remain this draft while host login mechanics stay host-specific.

## Default to headless APIs and public discovery

No visible application button is required. The reference config's `agent_ui` boolean defaults to
`false`; `GET /` returns public discovery JSON. `GET /.well-known/humangrant.json` always returns that
JSON, including when `agent_ui: true` enables the optional root demo UI. Serve discovery to all clients
without User-Agent filtering. Headless operation keeps the human consent, refusal, and revocation pages.

Discovery has these fields:

| Field | Meaning |
| --- | --- |
| `protocol_version` | `HumanGrant Protocol 0.1 Draft` |
| `origin` | Configured canonical public origin |
| `request_endpoint` | Absolute URL for `/v1/requests` |
| `session_endpoint` | Absolute URL for `/v1/session` |
| `specification_url` | Absolute URL for `/spec/v0.1.md` |
| `openapi_url` | Absolute URL for `/openapi.yaml` |
| `schema_url` | Absolute URL for `/schemas/protocol.json` |
| `agent_ui` | Whether the optional root demo UI is enabled |

Build all endpoint and document URLs from the configured origin, not request Host or forwarding headers.
An AI client must independently trust that origin and check the returned origin and URLs against it
before sending signed requests or credentials. Discovery is metadata, never authorization; it neither
establishes a human login nor grants access. Implement the signed request, status, claim and session
APIs regardless of whether a visible button is present.

## Keep enforcement in the target business service

A grant stores grantor, actor/public-key ID, original request, client, service, pairs, lifetime, revoke
time and audit ID. The target must check all bindings on every protected operation. Request and grant
permissions are immutable; a new action/resource needs new consent. A policy check must use current
account rights, not only the rights at issuance. Unknown actions, missing ownership and unavailable
policy checks fail closed. An introspection response alone does not execute an authorized transaction.

The notes reference performs the check and operation under one SQLite write lock. For another database
or external service, design the same ordering explicitly: access after committed revocation fails;
already committed operations are not undone. Caches need a bounded and documented revocation model.
No generic distributed-transaction, token-exchange, policy-language or OAuth adapter is included.

## Public client example

[clients/humangrant.py](../clients/humangrant.py) is independent of server modules. It implements the
signature profile, Markdown polling, permitted email invitations and one-time claim. It does not read
the database or bypass a human login. [scripts/e2e.py](../scripts/e2e.py) drives real HTTP endpoints with
real signatures; it requires a built Rust binary and has no Python-server fallback.
The library [Rust tests](../tests/protocol.rs) use the same HTTP dispatcher with a controlled clock.
The separate SQL tests intentionally examine database rules only, not authentication completeness.

## Map the UI without making it the authority

If a visible entry point is wanted, use [the button SVG](../assets/continue-with-human-beings.svg)
for an optional **Continue with human beings** button with an accessible name. An image alone is not
a working sign-in action. The optional root demo button in [ui.js](../examples/web/ui.js) creates an
independent agent identity, calls the request API, then reads actual Markdown. Headless clients call
the same API directly. In either case, the human link opens a separate same-origin review page.
It shows the requester key, untrusted purpose, exact service and permissions, current human account
and expiry. All choices start unchecked; approval is a separate POST.
A logged-in visitor sees these choices immediately, including on a new request. Reuse does not
extend the login lifetime. A changed or expired account must not submit the old confirmation.

Do not expose the human's cookie or private key to an AI. The human cookie and AI access credential are
separate stores and different proofs. Do not infer role from User-Agent or the string "human" or "AI".
Honor no-store response headers and keep identifiers and full invitation links out of public logs.

## Acceptance before enabling a host

Run the host's own login and business tests, the signature vector, schema checks, both notification
paths, scoped consent, expected-human mismatch, lost claim handling, revocation/current-rights removal,
concurrent decisions, CSRF, GET scanning, persistent mail limits and prompt synchronization checks.
Report the exact host version and executed tests. Do not claim third-party compatibility from the
presence of the skill file or an HTTP client library alone. Current limits are in
[verification.md](verification.md) and [SECURITY.md](../SECURITY.md).
