# Local verification record

**182 Python tests and 28 Rust tests passed. The compiled Rust server also passed the real HTTP flow.**
These results cover the headless-default changes for HumanGrant Protocol 0.1 Draft on
`feat/headless-discovery`. They are local validation, not a production deployment or release.
The configured source origin is `https://github.com/LIghtJUNction/humangrant.git`.
Machine-readable results are in [verification.json](verification.json).

## Checks actually executed

| Check | Result | Scope |
|---|---|---|
| `python scripts/check.py` | Passed | 18 Markdown files, 2 skills, 23 OpenAPI operations and 2 SVG button variants; local references and contracts. |
| `python scripts/sync_prompt.py --check` | Passed | Both README prompt blocks match their canonical sources. |
| `python -m pytest -q` | 182 passed | Python client, actual SQL rules, schemas, documentation, SMTP worker with fake transports, and JavaScript crypto exercised under Node. |
| `cargo fmt --check` | Passed | Rust formatting. |
| `cargo clippy --all-targets -- -D warnings` | Passed | Rust static checks, including test targets. |
| `cargo test --locked` | 28 passed | Actual Rust protocol and dispatcher tests, including default discovery, configured-origin URL construction, optional UI, signatures and human authorization. |
| `cargo build` | Passed | Reference Rust binary compiled. A generated `Cargo.lock` records the dependency resolution used here. |
| `node --check examples/web/ui.js` | Passed | Shared frontend syntax. |
| `node --check examples/web/webcrypto.js` | Passed | Browser crypto module syntax. |
| `python scripts/e2e.py --binary target/debug/humangrant` | Passed | Real local HTTP against the compiled Rust server; no substitute server. |
| `git diff --check` | Passed | Patch whitespace. |

The HTTP run checked:

- Default root JSON matches `/.well-known/humangrant.json` and the `Discovery` schema; advertised protocol documents are accessible.
- A forwarded human link requires genuine human proof and explicit consent before credential issuance.
- Permissions are narrowed; replay, wrong signing identities and unrelated resources are refused; revocation takes effect.
- A local `.eml` invitation reuses an existing human login while still requiring explicit consent.
- Expected-human mismatch, cancellation and authenticated refusal are enforced.
- Concurrent claims issue one credential exactly once.
- Server logs contain no issued credentials, cookies or recipient address.

Tests use temporary databases, generated test identities and a local mail spool. No real mail was sent.
No coverage percentage is claimed. SQL tests exercise the migration and SQL shipped with the service;
the HTTP tests separately exercise request parsing, cookies, human proof, consent and issuance together.

## Environment used

| Component | Version |
|---|---|
| Rust | 1.99.0 |
| Cargo | 1.99.0 |
| Python | 3.14.8 |
| Python SQLite | 3.54.0 |
| Node | 26.12.1 |
| pytest | 9.1.1 |
| cryptography | 50.0.2 |
| PyYAML | 6.0.3 |
| jsonschema | 4.26.0 |
| markdown-it-py | 4.2.0 |

## Unexecuted or unverified

- Interactive browser behavior and secure cookie behavior in a real browser.
- Cross-device HTTPS deployment, production operations and real SMTP/inbox delivery.
- Host-specific account and permission adapters, and installation inside third-party AI clients.
- The GitHub README copy button, performance and memory measurements, and an independent security audit.
- Compatibility with the declared minimum Rust version or a wider platform/version matrix.
- Remote CI, CodeQL and remote review; local checks are the acceptance criteria for this change.
- Release builds, signing, package publication and deployment.

The workflow in [.github/workflows/ci.yml](../.github/workflows/ci.yml) retains the declared validation
commands. A source push does not establish that any running service has been updated.
