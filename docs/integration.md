# Add login links to an existing application

HumanGrant lets an agent request a link, ask the person to sign in, and claim its own session. Keep the application's existing account system and authorization checks. The standalone Rust service uses notes as a small reference resource; adapt that policy at the host application's trusted boundary.

## Publish an agent entry point

Serve the discovery document at `/.well-known/humangrant.json` and plain instructions at `/agent.md`. The discovery response names the signed request, status, claim, cancel and session endpoints. Its URL values come from the configured canonical origin. Do not expose account lists, client credentials or resource inventories through discovery.

Advertise the document without adding a visible button:

```html
<link rel="humangrant" type="application/json" href="/.well-known/humangrant.json">
```

Also return an HTTP `Link` header with `rel="service-desc"` and `type="application/json"`. Keep the normal website free of HumanGrant forms, dashboards and login controls. Agents can read public discovery regardless of User-Agent; signed requests enforce the actual access boundary.

## Reuse the real human login

The reference exposes `App::with_authenticator` and the `HumanAuthenticator` trait in [src/auth.rs](../src/auth.rs). Override `session_principal(db, cookie, now)` to validate the host's current session and return its stable account principal. Return `None` when the login is missing, expired, logged out or invalid. The override is authoritative and is checked again at confirmation.

A valid login shows the account and requested access immediately. Otherwise, use the host's normal sign-in, then return to the same human link. Preserve request identity across that handoff. Never accept a posted account ID, requester claim or URL parameter as proof of login. Keep host-specific login endpoints and proof adapters documented separately from the agent protocol.

The built-in `PublicKeyAuthenticator` is a local reference mechanism: it checks an expiring challenge against an operator-provisioned public key. An agent must never obtain the human's identity file. The reference cookie is independent of the agent credential and does not extend its own lifetime when a link is opened.

## Confirm and issue a separate session

The human page shows the canonical service, actual account, requester identity, purpose, requested resources and expiry. The person explicitly confirms access. Revalidate the same account, expected-account restriction, Origin and request-bound CSRF token on submission. An authenticated GET can display choices but cannot change the request phase or approve access.

Only the original agent key may claim the approved request. Issue the credential once, store its hash, and bind it to the actor, grantor, client, service, approved permissions and expiry. Every protected operation checks current account rights, ownership, revocation and service policy. Keep that check and the operation in the same authority boundary.

The signed human grant-list and revocation endpoints support host account controls. They do not require a separate HumanGrant dashboard. The reference notes endpoints demonstrate that an approved read succeeds while unapproved operations fail.

## Verify the integration

Run [the repository checks](verification.md) and the host's own authentication tests. Exercise the complete public flow, an existing session on a second request, an expired login, account switching, refusal, wrong actor, one-time claim, revocation and current-rights removal. Check that ordinary page loads cause no authentication or approval writes.

Use [OpenAPI](../openapi.yaml), [field schemas](../schemas/protocol.json), [the protocol](../spec/v0.1.md), and [the signature fixture](../tests/fixtures/signature.json) for the exact contract. [clients/humangrant.py](../clients/humangrant.py) is an independent signed client; [scripts/e2e.py](../scripts/e2e.py) exercises the real Rust HTTP server.
