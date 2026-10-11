# Deployment and configuration

This is a deployment procedure for an **unpublished, unverified Rust reference**, not a claim that it
has run in production. Start with [verification.md](verification.md) and [SECURITY.md](../SECURITY.md).

## Local development

Generate a new empty state directory with `python examples/setup_demo.py --dir .state`.
It contains locally generated AI/Alice/Bob keys, a config with account public keys, and resource seeds.
Only the public keys go into the server config. Seed data is applied once to a newly initialized
database. Editing the seed lists later does not restore rights removed from an existing database.
There is no public endpoint for registering an arbitrary user ID as a logged-in account.

Run `cargo run -- serve .state/config.json`. Loopback HTTP requires `local_development: true` and a
loopback public origin. Do not expose that plain HTTP listener by changing its bind to `0.0.0.0`;
configuration validation rejects it. Protect the state directory and do not check it into Git.

## HTTPS and two devices

Choose your own controlled hostname and verified TLS certificate. The placeholder `YOUR_AUTH_HOST`
below is not a project domain. Change `public_origin` in the config to your canonical
`https://YOUR_AUTH_HOST`, set `local_development` to `false`, and keep `listen` at `127.0.0.1:8787`.
Restart using the same database. Configure the client with exactly that origin, without a path or
trailing slash, not one derived from a received purpose or arbitrary redirect.

A reverse proxy must terminate TLS, preserve the exact path/body/signed headers, and strip or ignore
untrusted forwarding values. The reference deliberately uses only the actual socket peer's address,
so a single proxy shares a source-limit bucket. Apply your own edge request-rate and connection limits.
Configure header/body read timeouts, a 16 KiB body limit and small header limits. Disable access logging
for `/human/` and `/invite/` paths or remove capabilities before logging. Do not cache sensitive replies.

An illustrative Caddy site configuration follows. It is not deployed or validated here. Install and
validate the proxy according to your own platform. Add your organization's edge connection/rate policy;
this small example is not internet-scale denial-of-service protection.

```text
YOUR_AUTH_HOST {
    request_body {
        max_size 16KB
    }
    reverse_proxy 127.0.0.1:8787
}
```

TLS proxy configuration and certificate access are operator responsibilities. A LAN address using
plain HTTP is not the cross-device exception. Test from the second device using HTTPS, not the
server's `127.0.0.1` address. No credential or human private key is transferred to the AI as part of
this process. See the complete [two-device walkthrough](../examples/README.md#two-devices).

## SQLite and operations

Use one reference server process per database. Use a local filesystem, not a network share. WAL and
full synchronous mode are configured. Permissions and grants are checked and modified in immediate
transactions; no Redis or queue service is required. Do not remove migrations or reset a live database
to clear cooldown. There is one initial schema, not a production upgrade/rollback migration system.

Local administrator commands (not public HTTP backdoors):

```sh
cargo run -- permission-remove .state/config.json alice notes.read alice-note
cargo run -- account-disable .state/config.json alice
```

Both keep grant history and prevent subsequent access through stale authority. They do not send mail.
The initial account/resource seed config is not a general account-management API.

Database, WAL, backups, and outbox files can contain personal data and link capabilities. Protect them.
Long-term record pruning, account key rotation, deployment lockfiles and disaster recovery remain
operator work; no automatic solution or measured memory footprint is claimed.

## SMTP worker

The default `mail.mode: "local"` writes private `.eml` files to `mail.spool` and performs no SMTP calls.
Set `mail.mode: "disabled"` to disable mail while keeping forwarded links fully usable.
Set `mail.mode: "smtp-worker"` only after deliberate operator configuration. The Rust server stores
fixed-template jobs. [clients/smtp_worker.py](../clients/smtp_worker.py) is a bounded, one-pass Unix tool
for that outbox; it is not an arbitrary email-sending API and not a background service by default.

Operator environment variables:

| Variable | Meaning |
|---|---|
| `HG_SMTP_HOST` | Your SMTP server |
| `HG_SMTP_PORT` | 465 by default; set 587 for a suitable STARTTLS endpoint |
| `HG_SMTP_TLS` | `implicit` by default, or `starttls`; no cleartext fallback |
| `HG_SMTP_FROM` | Your fixed, permitted sender address |
| `HG_SMTP_USER`, `HG_SMTP_PASSWORD` | Optional credentials; do not print or commit them |
| `HG_SMTP_TIMEOUT` | 15 seconds by default; accepted range 1–120 |

Only after explicit authorization to send real mail:

```sh
python clients/smtp_worker.py --config .state/config.json --limit 10 --allow-network
```

Without `--allow-network` it refuses to run. It takes a local file lock, recovers crashed `sending`
operations as `delivery_unknown`, and processes at most the chosen batch size. It never automatically
retries `failed` or `delivery_unknown`. A successful final SMTP DATA response means
`transport_accepted`, not delivery. A timeout during DATA can mean the message was accepted without
a reply; re-sending could duplicate it. The operator's review, a new explicitly requested operation,
unchanged rate limits and the original request deadline govern any recovery.

Local spool recovery runs only in server startup, not when an administrator opens the database.
Do not mix local spool and SMTP workers against the same live configuration. Tests inject transport
objects and do not use this network command. No provider credentials, real sends, inbound receipts,
SMTP-provider compatibility or SPF/DKIM/DMARC deployment has been tested or configured here.

## Configured limits

All defaults and accepted ranges are implemented in [src/config.rs](../src/config.rs).
Recipient 60-second/3-hourly/5-daily, actor 10-hourly, direct-source 10-hourly, and service
100-hourly/500-daily limits apply transactionally across request IDs. The public response does not
reveal which other request or block caused suppression. The database privacy key keeps stable HMAC
counter identities across restarts. Request creation also has actor/source/service quotas.
Do not restore an old database casually: that can restore old counters, revocation or replay state.
