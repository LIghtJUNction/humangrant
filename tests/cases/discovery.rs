use super::*;

#[test]
fn home_advertises_machine_entry_without_starting_a_login() {
    let mut h = Harness::new();
    let home = h.browser("GET", "/", "", "", json!({}));
    assert_eq!(home.status, 200);
    assert_eq!(page_data(&home)["view"], "home");
    assert!(!home.headers.contains_key("Set-Cookie"));
    assert!(home.headers["Link"].contains("/.well-known/humangrant.json"));
    assert!(home.headers["Link"].contains("/agent.md"));

    let discovery = h.app.handle(HttpInput {
        method: "GET".into(),
        path: "/.well-known/humangrant.json".into(),
        headers: BTreeMap::from([
            ("host".into(), "attacker.example".into()),
            ("x-forwarded-host".into(), "attacker.example".into()),
        ]),
        body: vec![],
        source: "127.0.0.1".into(),
    });
    assert_eq!(discovery.status, 200);
    assert_eq!(discovery.headers["Cache-Control"], "no-store");
    assert!(!discovery.headers.contains_key("Set-Cookie"));
    let metadata = value(&discovery);
    assert_eq!(metadata["flow"], "human_login_link");
    assert_eq!(metadata["origin"], ORIGIN);
    assert_eq!(metadata["browser_entrypoint"], false);
    assert_eq!(metadata["authentication"], "ed25519-http-signatures");
    assert_eq!(
        metadata["request_endpoint"],
        format!("{ORIGIN}/v1/requests")
    );
    assert_eq!(
        metadata["claim_endpoint_template"],
        format!("{ORIGIN}/v1/requests/{{request_id}}/claim")
    );
    assert!(metadata.get("accounts").is_none());
    assert!(metadata.get("resources").is_none());

    let instructions = h.browser("GET", "/agent.md", "", "", json!({}));
    assert_eq!(instructions.status, 200);
    assert_eq!(
        instructions.headers["Content-Type"],
        "text/markdown; charset=utf-8"
    );
    assert!(std::str::from_utf8(&instructions.body)
        .unwrap()
        .contains("human_authorization_url"));
    let counts = h
        .app
        .store
        .atomic(|db, _| {
            Ok((
                db.query_row("SELECT count(*) FROM requests", [], |r| r.get::<_, i64>(0))?,
                db.query_row("SELECT count(*) FROM browser_sessions", [], |r| {
                    r.get::<_, i64>(0)
                })?,
            ))
        })
        .unwrap();
    assert_eq!(counts, (0, 0));
    assert_eq!(
        h.browser("POST", "/v1/requests", "", "", json!({})).status,
        401
    );
}

#[test]
fn removed_surfaces_are_unavailable_and_new_databases_have_no_mail_queue() {
    let mut h = Harness::new();
    let state = h.create(None);
    assert!(state.get("email_request_status").is_none());
    assert!(state.get("email_retry_after_seconds").is_none());
    let path = format!("/v1/requests/{}/email", text(&state, "request_id"));
    assert_eq!(h.send(1, "POST", &path, json!({}), "anonymous").status, 404);
    for path in ["/invite/unused", "/assets/continue-with-human-beings.svg"] {
        assert_eq!(h.browser("GET", path, "", "", json!({})).status, 404);
    }
    assert_eq!(
        h.browser("GET", "/human/grants", "", "", json!({})).status,
        404
    );
    assert_eq!(
        h.browser("POST", "/human/grants/unused/revoke", "", "", json!({}))
            .status,
        404
    );
    let count = h
        .app
        .store
        .atomic(|db, _| {
            Ok(db.query_row(
            "SELECT count(*) FROM sqlite_master WHERE name IN ('mail_operations','mail_blocks')",
            [], |r| r.get::<_, i64>(0),
        )?)
        })
        .unwrap();
    assert_eq!(count, 0);
}

#[test]
fn invalid_human_links_render_a_clean_error_without_creating_a_browser() {
    let mut h = Harness::new();
    let response = h.browser("GET", "/human/missing", "", "", json!({}));
    assert_eq!(response.status, 404);
    assert_eq!(response.headers["Content-Type"], "text/html; charset=utf-8");
    assert_eq!(page_data(&response)["view"], "invalid");
    assert!(!response.headers.contains_key("Set-Cookie"));
}
