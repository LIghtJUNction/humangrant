# Integration procedure

Source: https://github.com/LIghtJUNction/humangrant

Locate a matching source checkout and read `AGENTS.md`, `spec/v0.1.md`, `openapi.yaml`, `schemas/protocol.json` and `docs/integration.md`. An installed skill does not include or install the server.

## Discovery and human handoff

Expose `/.well-known/humangrant.json` and `/agent.md` on the canonical service origin. Advertise discovery in the HTTP `Link` header and HTML head. Keep the ordinary page free of visible HumanGrant login controls. Discovery is public metadata; request signatures authenticate agent operations.

The agent creates a request at `/v1/requests`, shares its `/human/{link}` URL, polls `/v1/requests/{id}/status.md`, then claims at `/v1/requests/{id}/claim`. Only the original signing identity can read or claim that request. Use the exact signature profile and fixture, not bearer-only requests.

## Host account boundary

Find the actual host account validator and protected business operation. Keep both authoritative. `HumanAuthenticator` in `src/auth.rs` is trusted server code. Override `session_principal(db, cookie, now)` to validate the current host login, including logout and expiry. Return its stable account principal, never a posted account ID.

A valid existing login displays confirmation immediately. Recheck the account and request-bound CSRF token on submission. Loading the human link cannot authenticate, approve or create an agent session. Test a second request in the same browser, account switching and an expired login.

Keep the effective permission check beside each protected operation. The built-in notes policy is a reference integration. Map real host actions/resources and enforce current ownership, account rights, expiry and revocation there.

## Checks

Run these from the HumanGrant checkout, and run the target project's own checks for its implementation:

```sh
python -m pip install -r requirements-dev.txt
python scripts/check.py
python -m pytest -q
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build
python scripts/e2e.py --binary target/debug/humangrant
```

For a local example:

```sh
python examples/setup_demo.py --dir .state
cargo run -- serve .state/config.json
```

Setup refuses a nonempty directory; choose a new empty directory rather than deleting current data. Verify discovery, one generated link, real account authentication, explicit consent and one-time agent claim. Check denied extra resources, wrong actor, expected-account mismatch, stale consent, replay, expiry, cancellation and revocation. Report only checks actually run.
