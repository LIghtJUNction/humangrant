# Security boundaries

**Unpublished draft. Not production-ready. No independent security audit.** Read the actual
[verification record](docs/verification.md). SQL tests and client cryptography tests do not prove
that the Rust server compiles or that an entire login flow works.

## Protect the right identity

An AI holds its own local Ed25519 key. A human account is provisioned by a trusted operator or
verified by the target project's existing server-side identity system. Email, possession of a
review link, caller-provided IDs, model names, User-Agent, and prompt text are not authentication.
The protocol establishes account permission, not biological-human presence.

The reference verifies registered public keys against one-use, expiring, browser-bound challenges.
Private keys remain local. The browser example reads a human identity file into that page's memory:
use it only on a trusted origin. A compromised origin can replace its JavaScript and steal an imported
key. The local CLI signing alternative avoids giving a private key to page JavaScript, but still
requires the human to verify the trusted origin and request context. Neither path is a hardware
security key, passkey certification, phishing-resistant identity claim, or account-recovery system.

Use separate human and AI identities. Do not give the human's key to the AI and then call the result
an independent AI identity. Demo public keys are generated locally; there are no fixed production
passwords or static private identities. The committed signature seed is an explicitly public test
vector only. Never use it for a real identity.

## Authorize the operation, not a login label

Every business call checks the actor, credential hash, grantor, exact action/resource, resource owner,
service, expiry, revocation, current account rights, and service policy. Request and grant bindings
are immutable. SQLite transactions serialize decisions and access. A business operation committed
before revocation may finish; revocation cannot undo past actions. Cross-service distributed atomicity
is not implemented. External services must recheck locally or use a trusted fail-closed authority call
with an appropriate transaction design; caching an introspection result indefinitely is unsafe.

Human login does not approve a grant. Opening links by GET does not authenticate or approve.
Human writes require an exact Origin, SameSite=Strict/HttpOnly cookie, and session-bound CSRF token.
Login rotates the cookie and consumes the challenge. Expected-human restrictions are enforced.
Mail refusal links can refuse an unfinished request or block future invitations; they cannot approve,
claim a credential, or revoke a completed human grant. Someone with a leaked mail refusal link can
cause denial of service by blocking that destination. Keep full invitation files private.

## Signed requests and transport

See the exact [signature profile](spec/v0.1.md#5-request-signatures-strict-profile). Mature libraries
perform Ed25519, SHA-256 and HMAC. Nonces persist in SQLite, signatures cover Authorization, and a
credential alone does not prove the original actor's key. Same token with a fresh signature is valid
session use; reusing a signed request is not. No token is returned in a URL. There is no token refresh,
agent sub-delegation, silent consent upgrade, wildcard permission, or administrator mapping.

Use HTTPS with a verified certificate outside explicit loopback development. Configure one canonical
public origin. The HTTP listener remains on loopback. Preserve request bytes through a trusted proxy;
do not trust forwarded headers, caller Host, callbacks, or redirects. Apply header, body, connection,
and global request-rate limits at the proxy. Direct-peer IP limits are intentionally shared behind
one proxy. This conservative limit does not reveal or trust spoofed X-Forwarded-For values.

The single-process synchronous example is not hardened against internet-scale denial of service or
slow clients without a correctly configured proxy. No load, memory, latency, platform or concurrency
capacity claims are made. Run only one reference server for a database; the optional SMTP worker uses
a separate local OS lock. Do not put the database on a shared network filesystem.

## Credentials, logs and storage

Access credentials are delivered once and stored only as SHA-256 hashes by the service. AI CLI key
and session files are created with mode 0600 on Unix and refuse overwrites. Protect the parent folder,
server configuration, SQLite database, WAL, backups, local spool and worker lock files. Existing parent
directory permissions are not silently changed. Windows ACL behavior has not been tested.

The server does not log request paths, headers, bodies, cookies, credentials, or full email addresses.
Audit records contain event IDs, actor and grantor IDs and times, not proofs or mail content. Reverse
proxy access logs can leak review and refusal link capabilities; disable those path logs or redact
them at source. Do not add generic HTTP request logging middleware that prints secrets.

Recipient/source counters use keyed HMAC. The key and necessary delivery data are stored in the local
protected database, not encrypted at rest by this implementation. Use disk/backups encryption where
needed. A full database compromise breaks confidentiality and authorization; this protocol is not a
remedy for a compromised trusted server. Automatic long-term audit and mail-content retention/pruning,
key rotation and backup/restore procedures are not implemented. Operators must design them without
resetting rate limits or resurrecting revoked sessions. A restored snapshot can restore old state;
handle disaster recovery as a security operation, not a casual database copy.

A lost claim response cannot be safely reissued by this draft. Revoke the old grant first; only then
create a new request with permission from the human. Never label a local save failure as success.

## Email safety

The sender, subject, link and body template are not supplied by the AI. Purpose text is clearly marked
as untrusted data; it cannot replace fixed instructions. Destination, actor, source and service limits
are stored transactionally. Counts are reserved before delivery, including failed and unknown outcomes.
Public replies intentionally hide recipient blocks and activity in other requests. A 202 response is
not proof of transport or delivery. TLS SMTP acceptance is not a destination receipt. SMTP DATA timeout
or a crashed sending operation is delivery_unknown and is not automatically retried.

Tests use local files or an injected SMTP object. Never test against real recipients. The optional
worker requires explicit network permission in its CLI. A block applies to all future invitations to
the normalized destination, including new AI keys. Provider-specific aliases and multiple addresses
for the same physical inbox are not resolved; service-wide limits still apply. The draft has no self-service unblock or delivery receipt API.
A transport may have started before a refusal or expiry committed; already submitted mail cannot be
recalled. It still cannot approve anything, and expired links do not extend authorization.

## Reporting a problem

Do not post credentials, cookies, full invitation links, private keys, database dumps or personal mail
in a public issue. No private security contact or enabled GitHub advisory channel has been verified
for this new repository. Request a private reporting channel from the repository maintainer using
non-sensitive wording before sending exploit details. This project has no published supported release
or security-response timetable yet.
