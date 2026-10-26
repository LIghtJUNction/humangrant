# Run the reference flow

**Status:** runnable-source procedure; the initialization environment did not have Rust. See the
[verification record](../docs/verification.md) before treating these steps as a passed end-to-end test.
The example has one independent AI CLI, one human review UI, and a protected notes API. There is no
mock login, private-server shortcut, payment call, or real test email.

## One machine, two identities

From the repository root, after installing the documented Python development requirements and Rust:

```sh
python examples/setup_demo.py --dir .state
cargo build
cargo run -- serve .state/config.json
```

The default config starts headless: opening <http://127.0.0.1:8787> returns discovery JSON, with no
visible application button. <http://127.0.0.1:8787/.well-known/humangrant.json> always provides public
discovery. It contains `protocol_version`, `origin`, `request_endpoint`, `session_endpoint`,
`specification_url`, `openapi_url`, `schema_url`, and `agent_ui`; endpoint and document URLs are absolute
and use the configured public origin. Trust that origin independently before using the URLs.
Discovery describes the service; it does not grant permission.

No root UI is needed for this walkthrough. To try the optional root demo button, set `"agent_ui": true`
in `.state/config.json` and restart the server; the default is `false`. The well-known discovery endpoint
and the human review, refusal, and revocation pages remain available in either mode. Discovery is
public without User-Agent filtering.

In a second terminal:

```sh
python clients/humangrant.py --local --key .state/ai.key.json request --purpose "Read one note" --permissions notes.read:alice-note notes.write:alice-note --expected-human alice --watch --session-out .state/ai-session.json
```

The CLI prints actual Markdown and the human-only review link. Forward that link to the human.
The human opens it and uses their local `.state/alice.key.json` file in the page. Only public key and
signature are sent; the page warns that the origin's JavaScript must be trusted. Do not send this file
to the AI. The server already has the human's public key from trusted demo setup; the submitted public
key is not automatically registered as an arbitrary account.

After verification, the page still has no approval. Choose only `notes.read` on `alice-note` and click
**Approve selected access**. Unchecked permissions stay denied. The CLI claims once with its own key.
Its session file is not Alice's browser cookie.

```sh
python clients/humangrant.py --local --key .state/ai.key.json read alice-note --session .state/ai-session.json
python clients/humangrant.py --local --key .state/ai.key.json write alice-note --content "This must fail" --session .state/ai-session.json
python clients/humangrant.py --local --key .state/ai.key.json read alice-other-note --session .state/ai-session.json
python clients/humangrant.py --local --key .state/ai.key.json read bob-note --session .state/ai-session.json
python clients/humangrant.py --local --key .state/ai.key.json session --session .state/ai-session.json
```

Expected results: first read 200, write 403, unapproved Alice resource 403, Bob resource 403.
The context reports `actor.kind = ai`, original AI identity, `grantor_id = alice`, service, expiry,
audit ID and one effective permission. A direct human request is distinct:

```sh
python clients/humangrant.py --local --key .state/alice.key.json read alice-note
```

That uses Alice's registered signature and returns `actor.kind = human`. An unregistered AI's key
without a valid granted credential cannot obtain the same direct-account access.

## Local email path

Create a fresh request (do not reuse a succeeded one). Copy its real request ID into `REQUEST_ID`.
Only after permission to contact the address, submit:

```sh
python clients/humangrant.py --local --key .state/ai.key.json email "$REQUEST_ID" --email recipient@example.invalid --operation invite-one
```

The example address is reserved for documentation, not a real destination. Default local mode writes
one fixed-template file under `.state/outbox`. Open the newest `.eml` locally and follow its review link.
Use the same human verification and scope-selection steps as above. A repeat with the same operation
key does not create another mail task. Another intentional submission within cooldown is generically
accepted but internally suppressed; the AI cannot infer other mailbox activity. The refusal link is
separate, with explicit POST buttons for refusing or blocking. Opening it by GET has no such effect.

Do not print private invitation files into public logs. The automated HTTP test uses this local path
and inspects its one generated file, not a real email inbox.

## Human signs with a CLI instead of page JavaScript

On the human page, expand the local CLI alternative, create a challenge, and save only that public JSON
as `challenge.json` on the human's device. The human runs:

```sh
python clients/humangrant.py --local --key .state/alice.key.json sign-challenge --challenge-file challenge.json
```

Paste only the resulting `public_key` and `signature` into the page. Do not paste the identity file.
The CLI verifies the exact configured origin, challenge purpose, canonical format and deadline before
signing. The proof verifies account identity, not consent. Review and approve separately afterward.
Use a trusted `--origin` and omit `--local` for a remote HTTPS installation.

## Two devices

Configure a real trusted HTTPS origin using [deployment.md](../docs/deployment.md).
`HG_ORIGIN` below means your operator-supplied canonical HTTPS origin, not a URL taken from arbitrary
requester text. `REQUEST_ID`, `GRANT_ID` and paths refer to real values from this run.

On **device A**, the AI creates and retains its own key:

```sh
python clients/humangrant.py keygen --out .state/device-a-ai.key.json
python clients/humangrant.py --origin "$HG_ORIGIN" --key .state/device-a-ai.key.json request --purpose "Read the approved note" --permissions notes.read:alice-note notes.write:alice-note --expected-human alice --watch --session-out .state/device-a-session.json
```

Forward the returned human link to **device B**. The human must already have their own registered
identity on device B (or use the target project's real server-verified login adapter). Provisioning a
human key is an operator/human action outside AI authority; do not transfer it through the AI. For a
local reference demonstration, a human can independently generate a key on device B with `keygen` and
send only the `public` command's output to the operator before the first database bootstrap.

The human opens the HTTPS link, verifies their account, selects only read access to the stated resource,
and approves. Device A's watcher independently claims. On device A:

```sh
python clients/humangrant.py --origin "$HG_ORIGIN" --key .state/device-a-ai.key.json read alice-note --session .state/device-a-session.json
python clients/humangrant.py --origin "$HG_ORIGIN" --key .state/device-a-ai.key.json write alice-note --content "Must be denied" --session .state/device-a-session.json
python clients/humangrant.py --origin "$HG_ORIGIN" --key .state/device-a-ai.key.json read bob-note --session .state/device-a-session.json
```

On device B, open `/human/grants` on the same origin and revoke. The next read from device A fails.
The human may also list/revoke with their own CLI; never give that key to the AI to run the command.
A historical `succeeded` request still remains succeeded after revocation; business access checks live
state. Neither one-machine loopback tests nor Node Web Crypto tests prove a real two-device TLS run.

## Automated public interface check

```sh
cargo build
python scripts/e2e.py --binary target/debug/humangrant
```

The runner creates a temporary local config, starts the supplied Rust binary, and uses independent
signed HTTP clients and cookie sessions. It completes the forwarded-link and local-mail paths with
real Ed25519 proofs, tests read-only access and denial, and checks revocation. It does not write fake
login state into the database. It fails when the Rust binary is absent; there is no fallback server.
Controlled-time race/expiry checks run separately in SQL and Rust dispatcher tests, without long waits.
