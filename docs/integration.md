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
This interface is not a claim that existing browser sessions for every host can be attached unchanged.

The HTTP schemas contain public-key/signature evidence for the reference proof. A different host login
mechanism needs its own documented host-bound verification endpoint or a fully specified proof adapter;
do not silently rename a cookie to a signature and claim wire compatibility. The public agent-facing
request/state/claim/session API can remain this draft while host login mechanics stay host-specific.

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

Use [the button SVG](../assets/continue-with-human-beings.svg) as an accessible visual asset. An image
alone is not a working sign-in action. The demo button in [ui.js](../examples/web/ui.js) creates an
independent agent identity, calls the request API, then reads actual Markdown. The human link opens a
separate same-origin review page. It shows the requester key, untrusted purpose, exact service and
permissions, current human account and expiry. All choices start unchecked; approval is a separate POST.

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
