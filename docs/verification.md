# Local verification record

**166 Python/SQLite/Node-backed test cases passed. The Rust server has not been compiled or run.**
This is a local source handoff for HumanGrant Protocol 0.1 Draft, not a verified release or a
production-readiness report. The source was created in an empty local workspace. The configured
Git origin is `https://github.com/LIghtJUNction/humangrant.git`. No commit or push was made.

## Checks actually executed

| Check | Result | Scope |
|---|---:|---|
| `tests/test_sql.py` | 68 passed | The migration and SQL statements shipped with the Rust service, executed with SQLite and a controlled clock. Includes scope restrictions, live rights, state transitions, concurrent claims, revocation, and persistent mail limits. |
| `tests/test_client.py` | 60 passed | The independent Python client, signatures, private files, origin binding, Markdown parsing, controlled polling, CLI entry points, and local demo setup. |
| `tests/test_smtp.py` | 19 passed | The optional worker with injected fake SMTP transports and temporary databases. Includes definite failure, uncertain DATA outcome, idempotency, crash recovery, and worker locking. No real SMTP connection. |
| `tests/test_contracts.py` | 12 passed | JSON Schema, OpenAPI operation contracts, state fixtures and phase definitions. This is not HTTP interoperability testing. |
| `tests/test_docs.py` | 6 passed | Skill checks, references, README prompt completeness, real temporary Git remote handling, synchronization, and CI command declarations. |
| `tests/test_browser_crypto.py` | 1 passed | The actual JavaScript crypto module under Node Web Crypto; cross-language signature equality, key consistency and state/challenge validation. Not a browser UI test. |
| `python scripts/check.py` | Passed | 16 Markdown files, 2 skills, 21 OpenAPI operations, 2 SVG button variants; references, schemas and included source paths. |
| `python scripts/sync_prompt.py --check` | Passed | The complete README copy block exactly matches `prompts/integrate.md`. |
| Python bytecode compilation | Passed | `clients/*.py`, `examples/*.py`, `scripts/*.py`, `tests/*.py`. |
| JavaScript syntax checks | Passed | `examples/web/ui.js` and `examples/web/webcrypto.js`. |
| SVG rendering | Completed and visually inspected | Wordmark and light/dark login buttons rendered with CairoSVG. Text was complete and unclipped in those renders. |

Executed commands:

```sh
python -m pytest -q
python scripts/check.py
python scripts/sync_prompt.py --check
python -m py_compile clients/*.py examples/*.py scripts/*.py tests/*.py
node --check examples/web/ui.js
node --check examples/web/webcrypto.js
```

The test run had no skipped tests or failures. Module counts and tool versions are also recorded in
[verification.json](verification.json). No coverage percentage is claimed. Tests do not send mail to
real recipients or invoke paid services.

### What these checks establish

The tested SQLite rules operate on the actual migration and SQL files used by the Rust source.
They are not a second, replacement authorization server. SQL test setup is not evidence of human
login verification. The Python and JavaScript tests exercise their actual client implementations
and a public test-key fixture. The fixture is not a usable production identity.

Both notification paths have Rust dispatcher tests and a real-HTTP test script in source. Neither
complete path has been executed against the Rust service in this environment. In particular,
passing SQL tests does not prove that HTTP request parsing, human authentication, cookie handling,
permission approval and credential issuance work together correctly.

## Attempted but not executed

The following commands were attempted, but the shell reported that `cargo` was not found:

```sh
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build
```

The container has no Rust compiler, Cargo, rustfmt or Clippy. Network access could not obtain the
toolchain or crate dependencies. These are **unexecuted checks**, not passing checks. The Rust
source has not been formatted by rustfmt. Compilation, formatting corrections and lint fixes
remain pending; compilation errors may still exist. No `Cargo.lock` was generated.

There are 17 Rust test functions in [tests/protocol.rs](../tests/protocol.rs), covering the actual
Rust application dispatcher and signed requests. Their presence does not establish that they
compile or pass.

The command below was also attempted:

```sh
python scripts/e2e.py --binary target/debug/humangrant
```

It exited with code 2 and the explicit message:

```text
UNEXECUTED: Rust binary is missing. Run cargo build; no substitute server will be used.
```

It did not start a substitute Python server, skip authentication, or report a successful flow.
The intended real-HTTP test uses public interfaces, genuine signatures, a temporary local spool,
and generated local test identities. It must be run after the Rust build succeeds.

## Environment used for the successful local checks

| Component | Version |
|---|---|
| Python | 3.13.5 |
| Python SQLite | 3.46.1 |
| pytest | 9.0.2 |
| cryptography | 46.0.4 |
| PyYAML | 6.0.3 |
| jsonschema | 4.26.0 |
| markdown-it-py | 4.2.0 |
| Node | 22.16.0 |
| CairoSVG | 2.8.2 |

These results apply to this environment. They do not establish a platform, browser, minimum Rust
version or third-party AI-product compatibility matrix.

## Remaining work and unverified behavior

The following have not been verified or completed:

- Rust formatting, compilation, static checks, the 17 Rust tests, the real HTTP flow and a reviewed
  dependency lockfile. They are required before calling the reference server runnable or tested.
- Actual browser interaction, secure cookie behavior in a browser, cross-device HTTPS deployment,
  and the protected example operating through that deployment.
- Real SMTP configuration, provider behavior and inbox delivery. Fake transport results and local
  `.eml` files do not prove delivery. SMTP DATA uncertainty is intentionally not retried automatically.
- Host-specific identity and permission adapters. The reference implements local registered-key
  verification and note-resource permissions; it is not a universal adapter for existing products.
- Installation and execution of either skill inside third-party AI clients. Local format and
  command checks are not product certification.
- The copy button on the target GitHub README. The remote repository was empty when inspected,
  and no source was pushed. Only local parsing and exact block synchronization were checked.
- Remote CI execution, performance or memory measurement, an independent security audit,
  production operations, database retention tooling, releases or package publication.

The workflow in [.github/workflows/ci.yml](../.github/workflows/ci.yml) declares the required checks.
It has not been run remotely. The commands in the README are instructions to execute on a machine
with the required toolchain, not a claim that the server ran in this container.
