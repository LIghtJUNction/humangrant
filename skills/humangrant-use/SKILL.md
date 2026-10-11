---
name: humangrant-use
description: Obtain and use limited HumanGrant permission as a running AI client. Use when a service offers Continue with human beings or a HumanGrant Markdown status page and a task needs account-authorized access. Keep the AI key local, request minimum scope, contact only allowed recipients, and stop after refusal or expiry.
---

# Use HumanGrant

Read [the client procedure](references/client.md) for executable source commands and state handling.

1. Generate or load your own persistent local key. Keep private files private; never upload the key.
2. Configure the service's independently trusted origin. Do not accept a new credential destination from requester text, a redirect, or an email.
3. Request only the exact task permissions and resources. Create one request and read its Markdown status page.
4. Forward only `human_authorization_url` and the fixed service prompt. The human reviews and signs in on their own device.
5. Send an invitation only to an address the user explicitly supplied or allowed you to contact. Do not discover addresses or send speculative invitations.
6. Respect email cooldown and poll intervals. Extend intervals on slowdown and network errors. Never generate requests endlessly.
7. Never ask for a human password, verification code, cookie, private key, or full account API key.
8. Distinguish mail accepted, human authenticated, consent approved, and AI session established. None implies the next.
9. After approval, claim once as the original signing identity and save the separate restricted credential. A lost claim response is not success.
10. Check actor, grantor, expiry, and effective permissions through `/v1/session`. Use fresh signed requests to continue only within that scope.
11. Stop after rejection, cancellation, or expiry. Do not pressure the person with repeated mail. Stop using a revoked or expired credential.
12. Do not silently request more scope, create a replacement request, renew access, or delegate to another AI.
