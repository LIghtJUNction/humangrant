# HumanGrant for agents

Create a login link, give it to the person, and continue after they sign in and
confirm the requested access. The ordinary website has no login button or
browser request builder. Read the discovery document to find the machine entry.

## Discover

Read `GET /.well-known/humangrant.json` on the trusted service origin. Its URLs
are generated from the server's configured origin. The page also advertises the
document through its HTTP `Link` header and HTML metadata.

Discovery is public metadata. Creating, polling, claiming, and cancelling a
request require this agent's Ed25519 HTTP signatures. Use the
[signature profile](../spec/v0.1.md), [OpenAPI](../openapi.yaml), and
[JSON schema](../schemas/protocol.json) for exact wire details.

## Create one link

Send a signed `POST /v1/requests` with the configured application, service,
purpose, and exact access needed for the task. Use `HumanGrant anonymous` until
the human has confirmed and the original agent has claimed its own credential.
The reference notes integration accepts this example body:

```json
{
  "client_id": "example-cli",
  "target_service": "notes",
  "purpose": "Read the note for this task",
  "requested_permissions": [
    {"action": "notes.read", "resource": "alice-note"}
  ]
}
```

These identifiers belong to the local example. For an integrated service, use
its configured client and resource identifiers. Never invent an account identity
or treat a supplied account ID as evidence of login.

## Wait for the person

Show the returned `human_authorization_url` to the person. They open that link on
their own device, use the site's existing login when available, and explicitly
confirm the displayed access. Opening the link alone does not approve it.

Poll the returned request using a signed `GET /v1/requests/{request_id}` or
`GET /v1/requests/{request_id}/status.md`. Wait at least `poll_after_seconds`
between reads and respect `Retry-After`. Stop on rejection, expiry, cancellation,
success, or an authentication error. Do not create repeated requests on failure.

## Continue

When the phase is `approved`, send one signed
`POST /v1/requests/{request_id}/claim` with `{}`. Save the returned credential
privately and use it with fresh signatures for the same agent. A signed
`GET /v1/session` verifies the resulting session and its current access.

The human's password, cookies, and private key stay on their device. Only the
original requesting agent can claim its separate credential. Claiming is
one-time; a lost response does not make the credential recoverable. Follow the
protocol's status check and revocation procedure before requesting replacement
access. Use `POST /v1/requests/{request_id}/cancel` to stop an unfinished request.
