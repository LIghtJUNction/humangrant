//! Real Rust dispatcher tests. These require Cargo; SQL/Python tests are not substitutes.
use base64::{
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
    Engine as _,
};
use ed25519_dalek::{Signer, SigningKey};
use humangrant::config::{AccountSeed, Config, ResourceSeed};
use humangrant::crypto;
use humangrant::db::Clock;
use humangrant::model::State;
use humangrant::{App, HttpInput, HttpOutput};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicI64, Ordering},
    Arc,
};

const ORIGIN: &str = "https://auth.example.test";
const START: i64 = 1_700_000_000;

struct TestClock(AtomicI64);
impl Clock for TestClock {
    fn now(&self) -> i64 {
        self.0.load(Ordering::SeqCst)
    }
}

fn key(seed: u8) -> SigningKey {
    // Public deterministic test identities only; never used by the deployed example.
    SigningKey::from_bytes(&[seed; 32])
}
fn public(seed: u8) -> String {
    URL_SAFE_NO_PAD.encode(key(seed).verifying_key().as_bytes())
}
fn value(output: &HttpOutput) -> Value {
    serde_json::from_slice(&output.body).unwrap()
}
fn text(value: &Value, field: &str) -> String {
    value[field].as_str().unwrap().to_string()
}
fn page_data(output: &HttpOutput) -> Value {
    let html = std::str::from_utf8(&output.body).unwrap();
    let text = html
        .split("<script id=\"hg-data\" type=\"application/json\">")
        .nth(1)
        .unwrap()
        .split("</script>")
        .next()
        .unwrap();
    serde_json::from_str(text).unwrap()
}
fn session_cookie(output: &HttpOutput) -> String {
    output.headers["Set-Cookie"]
        .split(';')
        .next()
        .unwrap()
        .to_string()
}

struct Browser {
    path: String,
    cookie: String,
    csrf: String,
}
struct Harness {
    app: App,
    clock: Arc<TestClock>,
    directory: PathBuf,
    serial: u64,
}

impl Harness {
    fn new() -> Self {
        let directory =
            std::env::temp_dir().join(format!("humangrant-test-{}", crypto::random_token()));
        let clock = Arc::new(TestClock(AtomicI64::new(START)));
        let mut config = Config {
            public_origin: ORIGIN.into(),
            database: directory.join("state.db"),
            accounts: vec![
                AccountSeed {
                    id: "alice".into(),
                    public_key: public(2),
                },
                AccountSeed {
                    id: "bob".into(),
                    public_key: public(3),
                },
            ],
            resources: vec![
                ResourceSeed {
                    id: "alice-note".into(),
                    owner_id: "alice".into(),
                    content: "Alice private note".into(),
                    permissions: vec!["notes.read".into(), "notes.write".into()],
                },
                ResourceSeed {
                    id: "alice-other-note".into(),
                    owner_id: "alice".into(),
                    content: "Not requested".into(),
                    permissions: vec!["notes.read".into(), "notes.write".into()],
                },
                ResourceSeed {
                    id: "bob-note".into(),
                    owner_id: "bob".into(),
                    content: "Bob private note".into(),
                    permissions: vec!["notes.read".into(), "notes.write".into()],
                },
            ],
            ..Config::default()
        };
        config.mail.spool = directory.join("outbox");
        let app = App::new(config, clock.clone()).unwrap();
        Self {
            app,
            clock,
            directory,
            serial: 0,
        }
    }
    fn advance(&self, seconds: i64) {
        self.clock.0.fetch_add(seconds, Ordering::SeqCst);
    }
    fn signed_input(
        &mut self,
        actor: u8,
        method: &str,
        path: &str,
        body: Value,
        token: &str,
    ) -> HttpInput {
        self.serial += 1;
        let mut nonce = [0u8; 24];
        nonce[16..].copy_from_slice(&self.serial.to_be_bytes());
        let nonce = URL_SAFE_NO_PAD.encode(nonce);
        let bytes = if method == "GET" {
            vec![]
        } else {
            serde_json::to_vec(&body).unwrap()
        };
        let digest = format!("sha-256=:{}:", STANDARD.encode(Sha256::digest(&bytes)));
        let public = public(actor);
        let now = self.clock.now();
        let parameters =
            crypto::signature_params(now, now + 60, &nonce, &crypto::key_id(&public).unwrap());
        let authorization = format!("HumanGrant {token}");
        let base = crypto::signature_base(
            method,
            &format!("{ORIGIN}{path}"),
            &digest,
            &public,
            &authorization,
            &parameters,
        );
        let signature = STANDARD.encode(key(actor).sign(base.as_bytes()).to_bytes());
        let headers = BTreeMap::from([
            ("content-type".into(), "application/json".into()),
            ("content-digest".into(), digest),
            ("x-hg-key".into(), public),
            ("authorization".into(), authorization),
            ("signature-input".into(), format!("hg={parameters}")),
            ("signature".into(), format!("hg=:{signature}:")),
        ]);
        HttpInput {
            method: method.into(),
            path: path.into(),
            headers,
            body: bytes,
            source: "127.0.0.1".into(),
        }
    }
    fn send(
        &mut self,
        actor: u8,
        method: &str,
        path: &str,
        body: Value,
        token: &str,
    ) -> HttpOutput {
        let input = self.signed_input(actor, method, path, body, token);
        self.app.handle(input)
    }
    fn browser(
        &mut self,
        method: &str,
        path: &str,
        cookie: &str,
        csrf: &str,
        body: Value,
    ) -> HttpOutput {
        self.app.handle(HttpInput {
            method: method.into(),
            path: path.into(),
            headers: BTreeMap::from([
                ("content-type".into(), "application/json".into()),
                ("origin".into(), ORIGIN.into()),
                ("cookie".into(), cookie.into()),
                ("x-hg-csrf".into(), csrf.into()),
            ]),
            body: if method == "GET" {
                vec![]
            } else {
                serde_json::to_vec(&body).unwrap()
            },
            source: "127.0.0.1".into(),
        })
    }
    fn create(&mut self, expected: Option<&str>) -> Value {
        let response = self.send(
            1,
            "POST",
            "/v1/requests",
            json!({"client_id":"example-cli",
            "target_service":"notes","purpose":"Read one note", "expected_human_id":expected,
            "requested_permissions":[{"action":"notes.read","resource":"alice-note"},
                {"action":"notes.write","resource":"alice-note"}]}),
            "anonymous",
        );
        assert_eq!(response.status, 201);
        value(&response)
    }
    fn open(&mut self, state: &Value) -> Browser {
        let path = text(state, "human_authorization_url")
            .strip_prefix(ORIGIN)
            .unwrap()
            .to_string();
        let response = self.browser("GET", &path, "", "", json!({}));
        assert_eq!(response.status, 200);
        Browser {
            path,
            cookie: session_cookie(&response),
            csrf: text(&page_data(&response), "csrf"),
        }
    }
    fn authenticate(&mut self, browser: &mut Browser, human: u8) -> HttpOutput {
        let begin = self.browser(
            "POST",
            &format!("{}/begin", browser.path),
            &browser.cookie,
            &browser.csrf,
            json!({}),
        );
        assert_eq!(begin.status, 200);
        let challenge = text(&value(&begin), "challenge");
        let proof = json!({"public_key":public(human),"signature":STANDARD.encode(key(human).sign(challenge.as_bytes()).to_bytes())});
        let result = self.browser(
            "POST",
            &format!("{}/verify", browser.path),
            &browser.cookie,
            &browser.csrf,
            proof,
        );
        if result.status == 200 {
            browser.cookie = session_cookie(&result);
            browser.csrf = text(&value(&result), "csrf");
        }
        result
    }
    fn approve(&mut self, browser: &Browser) -> HttpOutput {
        self.browser("POST",&format!("{}/approve",browser.path),&browser.cookie,&browser.csrf,
            json!({"permissions":[{"action":"notes.read","resource":"alice-note"}],"expires_at":START+1800}))
    }
    fn authorized(&mut self) -> (Value, Value, Browser) {
        let state = self.create(Some("alice"));
        let mut browser = self.open(&state);
        assert_eq!(self.authenticate(&mut browser, 2).status, 200);
        assert_eq!(self.approve(&browser).status, 200);
        let issued = self.send(
            1,
            "POST",
            &format!("/v1/requests/{}/claim", text(&state, "request_id")),
            json!({}),
            "anonymous",
        );
        assert_eq!(issued.status, 200);
        (state, value(&issued), browser)
    }
}
impl Drop for Harness {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.directory);
    }
}

#[test]
fn headless_discovery_is_public_and_uses_the_configured_origin() {
    let config: Config = serde_json::from_value(json!({})).unwrap();
    assert!(!config.agent_ui);
    let mut h = Harness::new();
    let mut expected = None;
    for path in ["/", "/.well-known/humangrant.json"] {
        let response = h.app.handle(HttpInput {
            method: "GET".into(),
            path: path.into(),
            headers: BTreeMap::from([
                ("host".into(), "untrusted.example".into()),
                ("x-forwarded-host".into(), "untrusted.example".into()),
                ("user-agent".into(), "Mozilla/5.0".into()),
            ]),
            body: vec![],
            source: "127.0.0.1".into(),
        });
        assert_eq!(response.status, 200);
        assert_eq!(
            response.headers["Content-Type"],
            "application/json; charset=utf-8"
        );
        assert_eq!(response.headers["Cache-Control"], "no-store");
        assert!(!response.headers.contains_key("Set-Cookie"));
        let data = value(&response);
        assert_eq!(
            data,
            json!({
                "protocol_version": "HumanGrant Protocol 0.1 Draft",
                "origin": ORIGIN,
                "request_endpoint": format!("{ORIGIN}/v1/requests"),
                "session_endpoint": format!("{ORIGIN}/v1/session"),
                "specification_url": format!("{ORIGIN}/spec/v0.1.md"),
                "openapi_url": format!("{ORIGIN}/openapi.yaml"),
                "schema_url": format!("{ORIGIN}/schemas/protocol.json"),
                "agent_ui": false,
            })
        );
        if let Some(ref previous) = expected {
            assert_eq!(&data, previous);
        }
        expected = Some(data);
    }
    assert_eq!(
        h.browser("GET", "/v1/session", "", "", json!({})).status,
        401
    );
    assert_eq!(
        h.browser("POST", "/.well-known/humangrant.json", "", "", json!({}))
            .status,
        404
    );
}

#[test]
fn agent_ui_is_opt_in_and_preserves_discovery_and_human_pages() {
    let mut h = Harness::new();
    h.app.config.agent_ui = serde_json::from_value::<Config>(json!({"agent_ui": true}))
        .unwrap()
        .agent_ui;
    let root = h.browser("GET", "/", "", "", json!({}));
    assert_eq!(root.status, 200);
    assert_eq!(root.headers["Content-Type"], "text/html; charset=utf-8");
    assert_eq!(page_data(&root)["view"], "agent");
    let discovery = h.browser("GET", "/.well-known/humangrant.json", "", "", json!({}));
    assert_eq!(discovery.status, 200);
    assert_eq!(value(&discovery)["agent_ui"], true);
    let state = h.create(Some("alice"));
    let browser = h.open(&state);
    assert!(!browser.csrf.is_empty());
}

#[test]
fn public_signature_vector_verifies_in_rust() {
    let vector: Value = serde_json::from_str(include_str!("fixtures/signature.json")).unwrap();
    let headers = vector["headers"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.to_ascii_lowercase(), v.as_str().unwrap().into()))
        .collect();
    let proof = crypto::verify_http(
        "POST",
        "/v1/requests",
        &headers,
        text(&vector, "body_utf8").as_bytes(),
        ORIGIN,
        START,
    )
    .unwrap();
    assert_eq!(proof.actor_id, text(&vector, "actor_id"));
    assert!(crypto::verify_http(
        "PUT",
        "/v1/requests",
        &headers,
        text(&vector, "body_utf8").as_bytes(),
        ORIGIN,
        START
    )
    .is_err());
}

#[test]
fn markdown_is_the_same_state_object_as_json() {
    let state: State = serde_json::from_str(include_str!("fixtures/state.json")).unwrap();
    assert_eq!(state.markdown().unwrap(), include_str!("fixtures/state.md"));
}

#[test]
fn forwarded_link_flow_enforces_reduced_scope_and_actor() {
    let mut h = Harness::new();
    let (_, issued, _) = h.authorized();
    let token = text(&issued, "access_token");
    let read = h.send(1, "GET", "/v1/notes/alice-note", json!({}), &token);
    assert_eq!(read.status, 200);
    assert_eq!(value(&read)["context"]["actor"]["kind"], "ai");
    assert_eq!(value(&read)["context"]["grantor_id"], "alice");
    assert_eq!(
        h.send(
            1,
            "PUT",
            "/v1/notes/alice-note",
            json!({"content":"blocked"}),
            &token
        )
        .status,
        403
    );
    assert_eq!(
        h.send(1, "GET", "/v1/notes/bob-note", json!({}), &token)
            .status,
        403
    );
    assert_eq!(
        h.send(1, "GET", "/v1/notes/alice-other-note", json!({}), &token)
            .status,
        403
    );
    assert_eq!(
        h.send(4, "GET", "/v1/notes/alice-note", json!({}), &token)
            .status,
        401
    );
    let direct = h.send(2, "GET", "/v1/notes/alice-note", json!({}), "anonymous");
    assert_eq!(direct.status, 200);
    assert_eq!(value(&direct)["context"]["actor"]["kind"], "human");
}

#[test]
fn authentication_without_consent_does_not_issue_a_session() {
    let mut h = Harness::new();
    let state = h.create(None);
    let mut browser = h.open(&state);
    assert_eq!(h.authenticate(&mut browser, 2).status, 200);
    let claim = h.send(
        1,
        "POST",
        &format!("/v1/requests/{}/claim", text(&state, "request_id")),
        json!({}),
        "anonymous",
    );
    assert_eq!(claim.status, 409);
    assert_eq!(
        h.send(1, "GET", "/v1/notes/alice-note", json!({}), "anonymous")
            .status,
        403
    );
}

#[test]
fn wrong_actor_cannot_read_or_claim_and_a_human_link_is_not_a_token() {
    let mut h = Harness::new();
    let state = h.create(None);
    let id = text(&state, "request_id");
    assert_eq!(
        h.send(
            4,
            "GET",
            &format!("/v1/requests/{id}/status.md"),
            json!({}),
            "anonymous"
        )
        .status,
        404
    );
    assert_eq!(
        h.send(
            4,
            "POST",
            &format!("/v1/requests/{id}/claim"),
            json!({}),
            "anonymous"
        )
        .status,
        404
    );
    let link = text(&state, "human_authorization_url")
        .rsplit('/')
        .next()
        .unwrap()
        .to_string();
    assert_eq!(
        h.send(1, "GET", "/v1/notes/alice-note", json!({}), &link)
            .status,
        401
    );
}

#[test]
fn expected_human_is_verified_not_taken_from_an_email() {
    let mut h = Harness::new();
    let state = h.create(Some("alice"));
    let mut browser = h.open(&state);
    let result = h.authenticate(&mut browser, 3);
    assert_eq!(result.status, 403);
    assert_eq!(value(&result)["error"], "expected_human_mismatch");
}

#[test]
fn scanner_get_does_not_authenticate_or_approve() {
    let mut h = Harness::new();
    let state = h.create(None);
    let browser = h.open(&state);
    let page = h.browser("GET", &browser.path, &browser.cookie, "", json!({}));
    assert_eq!(page_data(&page)["phase"], "waiting_human");
    assert!(page_data(&page)["human_id"].is_null());
    assert_eq!(
        h.browser(
            "GET",
            &format!("{}/approve", browser.path),
            &browser.cookie,
            "",
            json!({})
        )
        .status,
        404
    );
}

#[test]
fn csrf_and_session_fixation_are_rejected() {
    let mut h = Harness::new();
    let state = h.create(None);
    let mut browser = h.open(&state);
    assert_eq!(
        h.browser(
            "POST",
            &format!("{}/begin", browser.path),
            &browser.cookie,
            "wrong",
            json!({})
        )
        .status,
        403
    );
    let old_cookie = browser.cookie.clone();
    assert_eq!(h.authenticate(&mut browser, 2).status, 200);
    assert_ne!(old_cookie, browser.cookie);
    assert_eq!(
        h.browser(
            "POST",
            &format!("{}/reject", browser.path),
            &old_cookie,
            &browser.csrf,
            json!({})
        )
        .status,
        403
    );
}

#[test]
fn rejected_cancelled_and_expired_requests_cannot_be_claimed() {
    for action in ["rejected", "cancelled", "expired"] {
        let mut h = Harness::new();
        let state = h.create(None);
        let id = text(&state, "request_id");
        if action == "rejected" {
            let mut browser = h.open(&state);
            assert_eq!(h.authenticate(&mut browser, 2).status, 200);
            assert_eq!(
                h.browser(
                    "POST",
                    &format!("{}/reject", browser.path),
                    &browser.cookie,
                    &browser.csrf,
                    json!({})
                )
                .status,
                200
            );
        } else if action == "cancelled" {
            assert_eq!(
                h.send(
                    1,
                    "POST",
                    &format!("/v1/requests/{id}/cancel"),
                    json!({}),
                    "anonymous"
                )
                .status,
                200
            );
        } else {
            h.advance(601);
        }
        let checked = h.send(
            1,
            "GET",
            &format!("/v1/requests/{id}"),
            json!({}),
            "anonymous",
        );
        assert_eq!(value(&checked)["phase"], action);
        assert_eq!(value(&checked)["poll_after_seconds"], 0);
        assert!(
            h.send(
                1,
                "POST",
                &format!("/v1/requests/{id}/claim"),
                json!({}),
                "anonymous"
            )
            .status
                >= 400
        );
    }
}

#[test]
fn duplicate_approval_and_claim_do_not_issue_another_credential() {
    let mut h = Harness::new();
    let (state, _, browser) = h.authorized();
    assert_eq!(h.approve(&browser).status, 409);
    let result = h.send(
        1,
        "POST",
        &format!("/v1/requests/{}/claim", text(&state, "request_id")),
        json!({}),
        "anonymous",
    );
    assert_eq!(result.status, 409);
    assert_eq!(value(&result)["error"], "credential_already_issued");
    assert!(value(&result).get("access_token").is_none());
}

#[test]
fn revoke_preserves_history_but_removes_access() {
    let mut h = Harness::new();
    let (state, issued, mut browser) = h.authorized();
    let grants = h.browser("GET", "/human/grants", &browser.cookie, "", json!({}));
    browser.csrf = text(&page_data(&grants), "csrf");
    let revoke = h.browser(
        "POST",
        &format!("/human/grants/{}/revoke", text(&issued, "grant_id")),
        &browser.cookie,
        &browser.csrf,
        json!({}),
    );
    assert_eq!(revoke.status, 200);
    assert_eq!(
        h.send(
            1,
            "GET",
            "/v1/notes/alice-note",
            json!({}),
            &text(&issued, "access_token")
        )
        .status,
        401
    );
    let result = h.send(
        1,
        "GET",
        &format!("/v1/requests/{}", text(&state, "request_id")),
        json!({}),
        "anonymous",
    );
    assert_eq!(value(&result)["phase"], "succeeded");
    assert_eq!(value(&result)["grant_status"], "revoked");
}

#[test]
fn original_permission_removal_is_effective_immediately() {
    let mut h = Harness::new();
    let (_, issued, _) = h.authorized();
    h.app
        .store
        .remove_entitlement("alice", "notes.read", "alice-note")
        .unwrap();
    assert_eq!(
        h.send(
            1,
            "GET",
            "/v1/notes/alice-note",
            json!({}),
            &text(&issued, "access_token")
        )
        .status,
        403
    );
    let session = h.send(
        1,
        "GET",
        "/v1/session",
        json!({}),
        &text(&issued, "access_token"),
    );
    assert_eq!(value(&session)["effective_permissions"], json!([]));
}

#[test]
fn signature_replay_is_not_normal_session_reuse() {
    let mut h = Harness::new();
    let (_, issued, _) = h.authorized();
    let input = h.signed_input(
        1,
        "GET",
        "/v1/session",
        json!({}),
        &text(&issued, "access_token"),
    );
    let duplicate = HttpInput {
        method: input.method.clone(),
        path: input.path.clone(),
        headers: input.headers.clone(),
        body: input.body.clone(),
        source: input.source.clone(),
    };
    assert_eq!(h.app.handle(input).status, 200);
    assert_eq!(value(&h.app.handle(duplicate))["error"], "signature_replay");
    assert_eq!(
        h.send(
            1,
            "GET",
            "/v1/session",
            json!({}),
            &text(&issued, "access_token")
        )
        .status,
        200
    );
}

#[test]
fn polling_changes_query_time_not_state_change_time() {
    let mut h = Harness::new();
    let state = h.create(None);
    let path = format!("/v1/requests/{}", text(&state, "request_id"));
    let first = h.send(1, "GET", &path, json!({}), "anonymous");
    let second = h.send(1, "GET", &path, json!({}), "anonymous");
    assert_eq!(second.status, 429);
    let delay = value(&second)["retry_after_seconds"].as_i64().unwrap();
    assert!(delay >= 10);
    h.advance(delay);
    let third = h.send(
        1,
        "GET",
        &format!("{path}/status.md"),
        json!({}),
        "anonymous",
    );
    assert_eq!(third.status, 200);
    assert_eq!(
        third.headers["Content-Type"],
        "text/markdown; charset=utf-8"
    );
    let markdown = String::from_utf8(third.body).unwrap();
    assert!(markdown.contains(&format!(
        "status_updated_at: {}",
        value(&first)["status_updated_at"]
    )));
    assert!(markdown.contains(&format!("checked_at: {}", START + delay)));
}

#[test]
fn local_email_is_idempotent_private_and_does_not_extend_deadline() {
    let mut h = Harness::new();
    let state = h.create(None);
    let path = format!("/v1/requests/{}/email", text(&state, "request_id"));
    let body = json!({"email":"test@example.invalid","idempotency_key":"once"});
    let first = h.send(1, "POST", &path, body.clone(), "anonymous");
    let second = h.send(1, "POST", &path, body, "anonymous");
    assert_eq!(first.status, 202);
    assert_eq!(first.body, second.body);
    let files: Vec<_> = std::fs::read_dir(h.directory.join("outbox"))
        .unwrap()
        .collect();
    assert_eq!(files.len(), 1);
    let mail = std::fs::read_to_string(files[0].as_ref().unwrap().path()).unwrap();
    assert!(mail.contains(&text(&state, "human_authorization_url")));
    assert!(!mail.contains("private_key"));
    assert!(!String::from_utf8(first.body)
        .unwrap()
        .contains("test@example.invalid"));
    let checked = h.send(
        1,
        "GET",
        &format!("/v1/requests/{}", text(&state, "request_id")),
        json!({}),
        "anonymous",
    );
    assert_eq!(value(&checked)["expires_at"], state["expires_at"]);
    let mut browser = h.open(&state);
    assert_eq!(h.authenticate(&mut browser, 2).status, 200);
    assert_eq!(h.approve(&browser).status, 200);
    assert_eq!(
        h.send(
            1,
            "POST",
            &format!("/v1/requests/{}/claim", text(&state, "request_id")),
            json!({}),
            "anonymous"
        )
        .status,
        200
    );
}

#[test]
fn concurrent_claims_using_separate_connections_issue_exactly_once() {
    let mut h = Harness::new();
    let state = h.create(None);
    let mut browser = h.open(&state);
    assert_eq!(h.authenticate(&mut browser, 2).status, 200);
    assert_eq!(h.approve(&browser).status, 200);
    let path = format!("/v1/requests/{}/claim", text(&state, "request_id"));
    let mut threads = vec![];
    for _ in 0..2 {
        let input = h.signed_input(1, "POST", &path, json!({}), "anonymous");
        let config = h.app.config.clone();
        let clock = h.clock.clone();
        threads.push(std::thread::spawn(move || {
            App::new(config, clock).unwrap().handle(input).status
        }));
    }
    let mut statuses: Vec<_> = threads
        .into_iter()
        .map(|thread| thread.join().unwrap())
        .collect();
    statuses.sort_unstable();
    assert_eq!(statuses, vec![200, 409]);
}

#[test]
fn invalid_origin_and_public_plain_http_are_rejected() {
    let mut config = Config {
        public_origin: "http://example.test".into(),
        local_development: true,
        ..Config::default()
    };
    assert!(config.validate().is_err());
    config.public_origin = "http://127.0.0.1:8787".into();
    assert!(config.validate().is_ok());
    config.listen = "0.0.0.0:8787".into();
    assert!(config.validate().is_err());
}

#[path = "cases/existing_login.rs"]
mod existing_login;
