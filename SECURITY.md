# Security boundaries

HumanGrant authenticates an agent separately from the person who approves its access. The human keeps their account login and credentials. The agent receives a key-bound session limited by the approved request and current account rights. Read the [protocol](spec/v0.1.md) for the wire contract and [verification](docs/verification.md) for reproducible checks.

## Identity and confirmation

A human link identifies a request; it does not authenticate the account or authorize a claim. Public discovery, User-Agent values, model names, purpose text and caller-provided IDs also grant no authority. The host must validate its real account session on both review and confirmation.

The reference verifies operator-provisioned public keys with one-use, expiring, browser-bound challenges. Its browser key-file option reads the private file in page memory and therefore requires a trusted origin. The local CLI-signature alternative keeps that private key outside page JavaScript. Integrations should reuse the host's existing account login.

Human GET requests display information without approving access or creating an agent session. Confirmation requires the exact Origin, a SameSite=Lax/HttpOnly browser cookie and a request/account-bound CSRF token. Login rotates the reference cookie. Expected-account restrictions are checked again at submission. Account switching invalidates the old confirmation.

Only requested permissions currently grantable by the authenticated account are selectable. The person explicitly confirms the displayed selection. The server validates every granted pair against the request, consent, current ownership, account rights and service policy.

## Agent session

Signed requests use the exact [signature profile](spec/v0.1.md#5-request-signatures-strict-profile). The signature includes Authorization and the canonical target URI. Nonces persist in SQLite; replaying a signature fails. Reusing an unexpired token with a fresh signature is normal session use.

Only the original agent key can claim an approved request. The service issues the random credential once and stores its hash. The token never appears in a human link or status response. If the claim response is lost, the human must revoke the grant before a new authorized request. A failed local credential save is not a usable session.

Each protected operation checks actor, credential, grantor, client, service, exact action/resource, current ownership, expiry and revocation. The reference serializes these checks with the operation in SQLite. Revocation blocks later operations; it does not undo work already committed. Host services need the same ordering at their own authority boundary.

## Transport and storage

Use HTTPS outside explicit loopback development. Keep the reference listener on loopback behind a trusted TLS proxy. Preserve exact signed bytes and configure header, body-read, connection and edge rate limits. The service uses the direct socket peer as its source-limit identity and ignores untrusted forwarded headers.

Use one server process per local database. Protect configuration, database, WAL and backup files. Key and session files are private on Unix and refuse overwrites; deployment-specific Windows ACL policy requires separate verification. Request-source counters use a persistent keyed hash.

Keep full human-link paths, headers, cookies, keys, tokens and bodies out of logs. Audit records contain event IDs, actor and grantor IDs, and timestamps. Disable or redact reverse-proxy access logs for human-link routes. Public discovery includes protocol metadata only.

A compromised origin or database defeats that trusted boundary. Operators own disk encryption, retention, backup recovery and account-key rotation. Restoring an old snapshot can also restore old replay or revocation state. Preserve current authority when planning recovery.

## Reporting a problem

Do not post credentials, private keys, full human links or database dumps in a public issue. Request a private reporting channel from the maintainer before sharing sensitive exploit details. A reproducible local test and the affected commit help separate protocol behavior from deployment configuration.
