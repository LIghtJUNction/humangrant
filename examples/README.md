# Run the login-link flow

This example uses an independent agent CLI and a human browser. The notes API is a small protected resource for checking the resulting session. See [verification](../docs/verification.md) for automated checks.

## Start the reference service

From the repository root with Rust and the Python development requirements installed:

```sh
python examples/setup_demo.py --dir .state
cargo run -- serve .state/config.json
```

Setup generates separate agent, Alice and Bob identities in a new private directory. The service receives only their public account keys. Keep the human identity files on the human's device.

## Generate the link

In another terminal:

```sh
python clients/humangrant.py --local discover
python clients/humangrant.py --local --key .state/ai.key.json request --purpose "Read one note" --permissions notes.read:alice-note --expected-human alice
```

The request command returns JSON immediately. Share only `human_authorization_url` with the person, and keep the actual `request_id` as `REQUEST_ID` for polling:

```sh
python clients/humangrant.py --local --key .state/ai.key.json status "$REQUEST_ID" --watch --session-out .state/ai-session.json
```

The home page has no login button. The human opens the generated link, sees the service and request, and signs in. In this local reference, they select their own `.state/alice.key.json` file on the trusted page. Only the public key and challenge signature are submitted. Existing host integrations use their normal login instead.

After identity verification, the human reviews the stated access and clicks **Sign in for agent**. A valid existing login goes directly to this confirmation. The original agent watcher claims its separate session once; opening the link alone never grants access.

## Check the session

```sh
python clients/humangrant.py --local --key .state/ai.key.json session --session .state/ai-session.json
python clients/humangrant.py --local --key .state/ai.key.json read alice-note --session .state/ai-session.json
python clients/humangrant.py --local --key .state/ai.key.json write alice-note --content "Must be denied" --session .state/ai-session.json
python clients/humangrant.py --local --key .state/ai.key.json read bob-note --session .state/ai-session.json
```

The session identifies the agent separately from Alice. The approved read succeeds; the unapproved write and Bob's resource are denied. The human can revoke the grant through the host's account controls or their own signed client:

```sh
python clients/humangrant.py --local --key .state/alice.key.json grants
python clients/humangrant.py --local --key .state/alice.key.json revoke "$GRANT_ID"
```

Use the actual grant ID returned by the list. These human commands belong on the human's device. Revocation prevents subsequent access while preserving the historical request record.

## Local signature alternative

The human page also accepts a locally generated proof. Create a challenge there, save its public JSON as `challenge.json`, and run on the human's device:

```sh
python clients/humangrant.py --local --key .state/alice.key.json sign-challenge --challenge-file challenge.json
```

Submit only the resulting public key and signature to the page, then confirm access. This keeps the private key out of page JavaScript. The CLI checks the trusted origin, request context and challenge deadline before signing.

## Two devices

Configure an operator-controlled HTTPS origin as described in [deployment](../docs/deployment.md). On the agent device, use `--origin "$HG_ORIGIN"` instead of `--local`, and retain its own key. Send the returned human link to the person on the second device.

The person uses the host application's account login or their already registered reference identity. Only public account information is provisioned to the service. Their private key and browser cookie stay on their device. The agent polls and claims independently, then uses its separate credential with fresh signatures.

## Automated HTTP check

```sh
cargo build
python scripts/e2e.py --binary target/debug/humangrant
```

The runner starts the supplied Rust binary with temporary local state and uses real signed HTTP requests. It checks discovery, the human handoff, separate agent access and revocation. It requires the Rust binary and has no substitute server.
