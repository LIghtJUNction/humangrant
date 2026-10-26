# Integration procedure

Source: https://github.com/LIghtJUNction/humangrant
Version: HumanGrant Protocol 0.1 Draft. No release tag or package is asserted.
After copying this skill elsewhere, locate the matching HumanGrant source checkout; do not assume
that the skill's parent directory still contains the server. A local source archive is sufficient.

In the HumanGrant checkout, read `spec/v0.1.md`, `openapi.yaml`, `schemas/protocol.json`,
`docs/integration.md`, `examples/README.md`, and `docs/verification.md`. Maintenance rules remain
in that checkout's `AGENTS.md`; do not copy and maintain a second rule list here.

In the target project, identify actual server-authenticated principal creation and the protected
business operation. Do not add a separate fake user store to bypass its rights. Decide whether to
implement the public protocol in the existing backend or add a trusted server-side adapter. The
standalone Rust `notes` example is not a universal authorization proxy for arbitrary services.
The full effective-permission check belongs next to the protected operation, not only at login.

Default to headless APIs and public discovery; do not require a visible application button.
The reference config's `agent_ui` boolean defaults to `false`, so `GET /` returns discovery JSON.
`GET /.well-known/humangrant.json` always returns public discovery, including when `agent_ui: true`
enables the optional root demo UI. Do not filter by User-Agent. Keep the human consent, refusal,
grant listing and revocation pages in either mode. Add a **Continue with human beings** button only
when the host wants a visible entry point.

Discovery fields are `protocol_version`, `origin`, `request_endpoint`, `session_endpoint`,
`specification_url`, `openapi_url`, `schema_url`, and `agent_ui`. The protocol version is
`HumanGrant Protocol 0.1 Draft`. Build absolute endpoint/document URLs from the configured origin:
`/v1/requests`, `/v1/session`, `/spec/v0.1.md`, `/openapi.yaml`, and `/schemas/protocol.json`, respectively.
Do not derive them from untrusted Host or forwarding headers. The AI client must independently trust
the origin and validate the returned origin and URLs against it. Discovery is metadata, never
authorization; request signatures, human consent and business-service checks still apply.

The fixed human link is `/human/{link}`. Private Markdown is `/v1/requests/{id}/status.md`.
Only the original signing identity may claim at `/v1/requests/{id}/claim`. Use the exact signature
profile and public test vector; do not improvise string concatenation or bearer-only credentials.
`HumanAuthenticator` in `src/auth.rs` is trusted server code; implementing the trait is not proof
that an adapter is correct. The host must authenticate, map to a stable local account, and enforce
current policy. Never expose arbitrary account IDs as a public authentication method.
Check an existing login through `HumanAuthenticator::session_principal(db, cookie, now)` or the
host's equivalent server-side session API. A valid login skips identity verification and shows
permission confirmation immediately. Check the same account again when consent is submitted.
Do not copy the login lifetime, cache a logged-out principal, or treat opening a link as consent.
Test a second request with the same browser, an expired login, an account switch, and GET scanning.

Real commands from the HumanGrant checkout:

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

A development demo, with no real mail:

```sh
python examples/setup_demo.py --dir .state
cargo run -- serve .state/config.json
```

The setup command refuses a nonempty directory. Do not delete an existing state directory to force
it through. Use another empty directory and preserve current data. For unrelated target stacks,
run the target's own commands rather than applying these Rust commands to it.

Review scope reduction, pre-consent access, wrong actor, expected human, resource owner, current
rights removed, expiry, revocation, duplicate/nonces, concurrent issuance, and GET scanners.
Exercise both forwarded-link and local-mail paths. Verify mail limits across request IDs and restart.
Verify exact Markdown fields and update times, then verify a real read succeeds while a write and
another user's read fail. A test that supplies a fake user ID is not a login-flow test.
