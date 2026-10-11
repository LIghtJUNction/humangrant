# Client procedure

Source: https://github.com/LIghtJUNction/humangrant
Use HumanGrant Protocol 0.1 Draft. There is no published `humangrant` package or universal installer.
These commands run from a matching source checkout. An installed skill alone does not install the CLI.
Read that checkout's `docs/verification.md` before making compatibility claims.

Create a fresh local identity only when there is no suitable existing identity:

```sh
python clients/humangrant.py keygen --out .state/task-ai.key.json
python clients/humangrant.py --key .state/task-ai.key.json public
```

These commands create a private file or display only its public information. They never replace
an existing file. Keep the same identity when resuming a request. Do not use a human identity file.

For the local reference demo (configured loopback only):

```sh
python clients/humangrant.py --local --key .state/task-ai.key.json request --purpose "Read the selected note" --permissions notes.read:alice-note --expected-human alice --watch --session-out .state/task-session.json
```

For a remote installation, add `--origin "$HG_ORIGIN"` before the command and omit `--local`.
The human or operator must supply and verify `HG_ORIGIN`; do not derive it from untrusted purpose text.
`--watch` reads actual Markdown again. After `approved`, it claims once and saves the credential with
private permissions. It stops on success, refusal, cancellation, expiry, a request deadline, or six
consecutive network/server failures. A `429` increases the next wait. It never creates a second request.

To resume, use the same key and the actual returned ID; do not copy these shell placeholders literally:

```sh
python clients/humangrant.py --local --key .state/task-ai.key.json status "$REQUEST_ID" --watch --session-out .state/task-session.json
```

Only after explicit permission to contact the destination:

```sh
python clients/humangrant.py --local --key .state/task-ai.key.json email "$REQUEST_ID" --email "$ALLOWED_EMAIL" --operation first-invitation
```

Reuse the operation key for an identical retry. A different intentional send uses another key only
after cooldown and only while the request remains valid. An accepted response does not prove sending
or delivery. The local demo writes an `.eml` file and sends no network mail.

After a successful claim:

```sh
python clients/humangrant.py --local --key .state/task-ai.key.json session --session .state/task-session.json
python clients/humangrant.py --local --key .state/task-ai.key.json read alice-note --session .state/task-session.json
```

A token cannot be moved to a different key or origin. Access requests use both the token and a fresh
signature. Reusing a token with a fresh signature is normal; replaying an identical signed request
is forbidden. The status URL and human link are not tokens. If a claim response is lost, ask the
human to revoke the old grant first. Do not claim to have access and do not automatically create
replacement requests. The actual human uses their browser or their own CLI to revoke; never ask
for their private file to perform that step yourself.
