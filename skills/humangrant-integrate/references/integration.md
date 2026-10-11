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

The fixed human link is `/human/{link}`. Private Markdown is `/v1/requests/{id}/status.md`.
Only the original signing identity may claim at `/v1/requests/{id}/claim`. Use the exact signature
profile and public test vector; do not improvise string concatenation or bearer-only credentials.
`HumanAuthenticator` in `src/auth.rs` is trusted server code; implementing the trait is not proof
that an adapter is correct. The host must authenticate, map to a stable local account, and enforce
current policy. Never expose arbitrary account IDs as a public authentication method.

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
