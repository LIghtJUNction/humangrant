# Verification

Run checks against the current source checkout. The workflow in [.github/workflows/ci.yml](../.github/workflows/ci.yml) runs the same required commands on pushes and pull requests.

```sh
python -m pip install -r requirements-dev.txt
python scripts/sync_prompt.py --check
python scripts/check.py
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
python -m pytest -q
node --check examples/web/ui.js
node --check examples/web/webcrypto.js
cargo build
python scripts/e2e.py --binary target/debug/humangrant
```

The Rust tests exercise the actual HTTP dispatcher, signatures, discovery and account/session state. Python tests cover independent client behavior, schemas, documentation, browser modules and the database rules shipped with the service. The HTTP runner starts the supplied Rust binary and completes the link, human authentication, consent and agent-claim flow through public endpoints.

For visual checks, open the home page and actual human links on desktop and mobile viewports. Check waiting, signed-in confirmation, success, rejection, expired and invalid states. Confirm that the home page contains no login entry and that merely loading a human link submits no decision.

Deployment-specific checks remain necessary for a host's real login adapter, cross-device HTTPS, TLS proxy settings and supported browsers. Report commands actually executed and their results with the commit being reviewed; these instructions make no test-count or deployment claims.
