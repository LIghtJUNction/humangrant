# HumanGrant maintenance rules

This file is the single source for repository maintenance rules.

- Read `spec/v0.1.md` before changing the wire protocol. This is an unpublished draft.
- Human approval is not a human session. Keep the grantor and the AI actor separate.
- Never accept a caller-supplied account ID as authentication. Never send a private key.
- All grants are a subset of the request, explicit consent, current account rights, and service policy.
- Preserve unrelated files and uncommitted work. Do not push, publish, or send real mail without permission.
- SQL security rules live in `migrations/0001.sql` and `src/sql/`. Do not bypass them.
- Do not log headers, cookies, tokens, full email addresses, or authorization-link paths.
- Tests use temporary databases, a controlled clock, and a local mail spool. Never send real test mail.
- Skills: `skills/humangrant-integrate/SKILL.md` and `skills/humangrant-use/SKILL.md`.
- Integration prompt source: `prompts/integrate.md`. Run `python scripts/sync_prompt.py` after editing.
- Checks: `python scripts/check.py`; `python -m pytest -q`; `cargo fmt --check`;
  `cargo clippy --all-targets -- -D warnings`; `cargo test`; `cargo build`.
- Full public-HTTP test: `python scripts/e2e.py --binary target/debug/humangrant`.
- Report executed checks separately from unexecuted checks. Never infer runtime success from source review.
