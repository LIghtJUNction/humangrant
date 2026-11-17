---
name: humangrant-use
description: Generate a HumanGrant login link and wait for a human to sign in for an AI agent. Use when a service exposes HumanGrant discovery or a HumanGrant status endpoint and a task needs account access. Keep the agent key local, request minimum access, and claim the approved session once.
---

# Use HumanGrant

Read [the client procedure](references/client.md) for executable commands.

1. Establish the service's trusted canonical origin. Read `/.well-known/humangrant.json` and `/agent.md`, or follow its `rel="humangrant"` discovery link. Check that all credential destinations remain on that origin.
2. Generate or reuse the agent's own local signing key. Keep the same identity when resuming. Never use a human identity file.
3. Create one request with the exact permissions and resources needed for the task. Read the returned `request_id`, `human_authorization_url` and polling interval.
4. Share only the human login URL and the fixed service prompt. Let the person sign in and confirm on their own device. Never ask for their password, verification code, cookie, private key or account API key.
5. Poll with the original agent key. Respect the server's interval and `Retry-After`; use bounded backoff for network errors. Stop on refusal, cancellation, expiry or authentication failure.
6. After approval, claim once and save the separate credential privately. A lost claim response or failed local save is not a usable session; ask for revocation before a new authorized request.
7. Check actor, grantor, expiry and effective access through `/v1/session`, then continue with fresh signed requests within that scope.
8. Stop using revoked or expired access. Do not silently expand scope, create replacement requests, renew access or delegate the session.

The missing website button is intentional. Use discovery instead of searching the visual page for a login control.
