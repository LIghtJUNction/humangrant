# Deployment

Run HumanGrant behind a canonical HTTPS origin and connect it to the application's trusted account login. The local reference uses SQLite and operator-provisioned account keys. See [integration](integration.md) for existing-login adapters and [security](../SECURITY.md) for the account boundary.

## Local reference

```sh
python examples/setup_demo.py --dir .state
cargo run -- serve .state/config.json
```

The setup command requires an empty directory. It generates independent demo keys and puts only account public keys in server configuration. Seed records apply once to a new database. Keep the state directory private and outside Git.

Local HTTP requires `local_development: true` and a loopback public origin. The listener also stays on loopback. Open `http://127.0.0.1:8787` for the quiet home page; agents read `/.well-known/humangrant.json` and create the human link through the signed API.

## HTTPS

Set `public_origin` to the operator-controlled canonical HTTPS origin, set `local_development` to `false`, and keep `listen` on `127.0.0.1:8787`. Configure a trusted TLS reverse proxy to preserve the exact method, path, body and signed headers. The client uses that same configured origin.

Apply header, body-read and connection timeouts, a 16 KiB body limit and edge rate limits. Disable access logging for `/human/` paths or redact the link capability before logging. Preserve `Cache-Control: no-store`. The reference uses the actual socket peer for source limits; requests through one proxy share that bucket.

An illustrative Caddy configuration, using your own hostname and certificate setup:

```text
YOUR_AUTH_HOST {
    request_body {
        max_size 16KB
    }
    reverse_proxy 127.0.0.1:8787
}
```

For two devices, share the HTTPS human link. Loopback addresses refer to the device opening them. The human keeps their login and private key on their own device; the agent retains its separate key and session.

## State and operations

Use one server process per SQLite database on a local filesystem. WAL and full synchronous mode are configured. Preserve existing database files, replay records and revocations during upgrades. Removing a seed record from configuration does not remove current database rights. When upgrading an earlier configuration, remove its obsolete `mail` object; existing database records remain intact, and retired delivery tables are ignored.

Local operator commands change current authority while preserving grant history:

```sh
cargo run -- permission-remove .state/config.json alice notes.read alice-note
cargo run -- account-disable .state/config.json alice
```

Protect the configuration, database, WAL and backups. Record retention, backup recovery and account-key rotation belong to the operator's deployment plan. Restoring a snapshot can restore old authority and replay state.

[src/config.rs](../src/config.rs) defines request expiry, session expiry, poll interval and request-creation quotas. Defaults are a 600-second login link, a 3600-second maximum session and five-second polling. Creation limits apply per actor, socket source and service. HumanGrant creates links directly; no mail transport or background delivery worker is needed.
