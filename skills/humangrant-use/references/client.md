# Client procedure

Source: https://github.com/LIghtJUNction/humangrant

Run these commands from a matching source checkout. An installed skill alone does not install the CLI. For a remote service, use its independently trusted `--origin "$HG_ORIGIN"` and omit `--local`; the examples below use the loopback development server.

## Discover and create a link

Read public metadata without a private key:

```sh
python clients/humangrant.py --local discover
```

Generate a private agent identity only when no suitable identity already exists:

```sh
python clients/humangrant.py keygen --out .state/task-ai.key.json
```

Create one request. This returns the actual login URL immediately:

```sh
python clients/humangrant.py --local --key .state/task-ai.key.json request --purpose "Read the selected note" --permissions notes.read:alice-note --expected-human alice
```

Share `human_authorization_url` with the person. Keep the returned `request_id` as `REQUEST_ID` for the next command. The human signs in on their own device; never request their identity file or cookies.

## Wait and continue

```sh
python clients/humangrant.py --local --key .state/task-ai.key.json status "$REQUEST_ID" --watch --session-out .state/task-session.json
```

The watcher reads actual Markdown, respects polling limits, claims once after approval and writes a private session file. It stops on success, refusal, cancellation, expiry, authentication failure or bounded consecutive network errors. It never creates a replacement request. Reuse the same key to resume an existing request.

After a successful claim, verify the session:

```sh
python clients/humangrant.py --local --key .state/task-ai.key.json session --session .state/task-session.json
```

The token is bound to the agent key and service origin. Use it with a fresh signature for each request. The human link and status path carry no agent-session authority.

If a claim response is lost, have the human revoke the old grant before creating a new authorized request. The human uses their host account controls or their own signed client. Keep their private identity outside the agent's access.
