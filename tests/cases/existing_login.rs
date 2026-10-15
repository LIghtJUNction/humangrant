use super::*;
use humangrant::auth::{HumanAuthenticator, HumanPrincipal, PublicKeyAuthenticator};
use humangrant::error::Result;
use rusqlite::Connection;
use std::sync::Mutex;

fn review(h: &mut Harness, state: &Value, cookie: &str) -> (Browser, Value, HttpOutput) {
    let path = text(state, "human_authorization_url")
        .strip_prefix(ORIGIN)
        .unwrap()
        .to_string();
    let output = h.browser("GET", &path, cookie, "", json!({}));
    assert_eq!(output.status, 200);
    let data = page_data(&output);
    let cookie = if output.headers.contains_key("Set-Cookie") {
        session_cookie(&output)
    } else {
        cookie.to_string()
    };
    (
        Browser {
            path,
            cookie,
            csrf: text(&data, "csrf"),
        },
        data,
        output,
    )
}

fn phase(h: &mut Harness, state: &Value) -> String {
    h.app
        .store
        .atomic(|db, _| {
            Ok(db.query_row(
                "SELECT phase FROM requests WHERE id=?1",
                [text(state, "request_id")],
                |r| r.get(0),
            )?)
        })
        .unwrap()
}

#[test]
fn logged_in_browser_opens_new_request_and_approves_without_another_login() {
    let mut h = Harness::new();
    let (_, _, first) = h.authorized();
    let state = h.create(Some("alice"));
    let (second, data, output) = review(&mut h, &state, &first.cookie);
    assert_eq!(data["human_id"], "alice");
    assert_eq!(data["phase"], "waiting_human");
    assert_eq!(phase(&mut h, &state), "waiting_human");
    assert!(!output.headers.contains_key("Set-Cookie"));
    assert_ne!(first.csrf, second.csrf);
    let claim_path = format!("/v1/requests/{}/claim", text(&state, "request_id"));
    assert_eq!(
        h.send(1, "POST", &claim_path, json!({}), "anonymous")
            .status,
        409
    );
    assert_eq!(h.approve(&second).status, 200);
    let issued = h.send(1, "POST", &claim_path, json!({}), "anonymous");
    assert_eq!(issued.status, 200);
    let token = text(&value(&issued), "access_token");
    assert_eq!(
        h.send(1, "GET", "/v1/notes/alice-note", json!({}), &token)
            .status,
        200
    );
    assert_eq!(
        h.send(
            1,
            "PUT",
            "/v1/notes/alice-note",
            json!({"content":"not allowed"}),
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
    assert_eq!(h.approve(&second).status, 409);
}

#[test]
fn parallel_review_tabs_keep_the_login_but_cannot_exchange_confirmation_tokens() {
    let mut h = Harness::new();
    let (_, _, first) = h.authorized();
    let a = h.create(None);
    let b = h.create(None);
    let (review_a, _, _) = review(&mut h, &a, &first.cookie);
    let (review_b, _, _) = review(&mut h, &b, &first.cookie);
    assert_eq!(review_a.cookie, review_b.cookie);
    let wrong = Browser {
        path: review_b.path.clone(),
        cookie: review_b.cookie.clone(),
        csrf: review_a.csrf.clone(),
    };
    let output = h.approve(&wrong);
    assert_eq!(output.status, 403);
    assert_eq!(value(&output)["error"], "csrf_failed");
    assert_eq!(phase(&mut h, &b), "waiting_human");
    assert_eq!(h.approve(&review_a).status, 200);
    assert_eq!(h.approve(&review_b).status, 200);
}

#[test]
fn existing_login_can_refuse_without_authentication_or_automatic_approval() {
    let mut h = Harness::new();
    let (_, _, first) = h.authorized();
    let state = h.create(None);
    let (review, _, _) = review(&mut h, &state, &first.cookie);
    assert_eq!(
        h.browser(
            "GET",
            &format!("{}/approve", review.path),
            &review.cookie,
            &review.csrf,
            json!({})
        )
        .status,
        404
    );
    assert_eq!(phase(&mut h, &state), "waiting_human");
    assert_eq!(
        h.browser(
            "POST",
            &format!("{}/reject", review.path),
            &review.cookie,
            &review.csrf,
            json!({})
        )
        .status,
        200
    );
    assert_eq!(phase(&mut h, &state), "rejected");
    assert_eq!(h.approve(&review).status, 409);
}

#[test]
fn review_does_not_extend_login_and_expiry_is_rechecked_at_submission() {
    let mut h = Harness::new();
    let (_, _, first) = h.authorized();
    h.advance(1750);
    let state = h.create(None);
    let (reviewed, data, output) = review(&mut h, &state, &first.cookie);
    assert_eq!(data["human_id"], "alice");
    assert!(!output.headers.contains_key("Set-Cookie"));
    h.advance(51);
    assert_eq!(h.approve(&reviewed).status, 403);
    let (_, data, _) = review(&mut h, &state, &first.cookie);
    assert!(data["human_id"].is_null());
    assert_eq!(phase(&mut h, &state), "waiting_human");
}

#[test]
fn expected_account_and_current_permissions_remain_required() {
    let mut h = Harness::new();
    let (_, _, first) = h.authorized();
    let wrong_account = h.create(Some("bob"));
    let (reviewed, data, _) = review(&mut h, &wrong_account, &first.cookie);
    assert_eq!(data["human_id"], "alice");
    let refusal = h.approve(&reviewed);
    assert_eq!(refusal.status, 403);
    assert_eq!(value(&refusal)["error"], "expected_human_mismatch");
    assert_eq!(phase(&mut h, &wrong_account), "waiting_human");
    let state = h.create(Some("alice"));
    let (reviewed, _, _) = review(&mut h, &state, &first.cookie);
    h.app
        .store
        .remove_entitlement("alice", "notes.read", "alice-note")
        .unwrap();
    assert_eq!(h.approve(&reviewed).status, 403);
    assert_eq!(phase(&mut h, &state), "waiting_human");
    h.app
        .store
        .atomic(|db, _| {
            db.execute("UPDATE accounts SET enabled=0 WHERE id='alice'", [])?;
            Ok(())
        })
        .unwrap();
    let (_, data, _) = review(&mut h, &state, &first.cookie);
    assert!(data["human_id"].is_null());
    assert_eq!(h.approve(&reviewed).status, 403);
}

#[test]
fn forged_login_cookie_and_cross_site_confirmation_fail() {
    let mut h = Harness::new();
    let state = h.create(None);
    let (anonymous, data, output) = review(&mut h, &state, "hg_browser=alice; user_id=alice");
    assert!(data["human_id"].is_null());
    assert_eq!(h.approve(&anonymous).status, 403);
    let cookie = &output.headers["Set-Cookie"];
    assert!(
        cookie.contains("SameSite=Lax") && cookie.contains("HttpOnly") && cookie.contains("Secure")
    );
    let (_, _, first) = h.authorized();
    let (reviewed, _, _) = review(&mut h, &state, &first.cookie);
    let output = h.app.handle(HttpInput {
        method: "POST".into(), path: format!("{}/approve", reviewed.path),
        headers: BTreeMap::from([
            ("content-type".into(), "application/json".into()),
            ("origin".into(), "https://untrusted.example.test".into()),
            ("cookie".into(), reviewed.cookie), ("x-hg-csrf".into(), reviewed.csrf),
        ]),
        body: serde_json::to_vec(&json!({"permissions":[{"action":"notes.read","resource":"alice-note"}],"expires_at":START+300})).unwrap(),
        source: "127.0.0.1".into(),
    });
    assert_eq!(output.status, 403);
    assert_eq!(value(&output)["error"], "csrf_failed");
    assert_eq!(phase(&mut h, &state), "waiting_human");
}

// Test-only host session store. This tests the trusted adapter contract, not a host login product.
// Reference login end-to-end tests above use real public-key proofs, never this fixture.
struct HostAuth {
    token: String,
    account: Arc<Mutex<Option<String>>>,
    expires: i64,
}
impl HumanAuthenticator for HostAuth {
    fn authenticate(
        &self,
        db: &Connection,
        public: &str,
        challenge: &str,
        signature: &str,
    ) -> Result<HumanPrincipal> {
        PublicKeyAuthenticator.authenticate(db, public, challenge, signature)
    }
    fn session_principal(
        &self,
        _db: &Connection,
        cookie: &str,
        now: i64,
    ) -> Result<Option<HumanPrincipal>> {
        let found: Vec<_> = cookie
            .split(';')
            .map(str::trim)
            .filter_map(|s| s.strip_prefix("host_session="))
            .collect();
        if found.len() != 1 || found[0] != self.token || now >= self.expires {
            return Ok(None);
        }
        Ok(self
            .account
            .lock()
            .unwrap()
            .clone()
            .map(|account_id| HumanPrincipal { account_id }))
    }
}
fn host(h: &mut Harness) -> (String, Arc<Mutex<Option<String>>>) {
    let token = crypto::random_token();
    let account = Arc::new(Mutex::new(Some("alice".to_string())));
    h.app = App::with_authenticator(
        h.app.config.clone(),
        h.clock.clone(),
        Box::new(HostAuth {
            token: token.clone(),
            account: account.clone(),
            expires: START + 300,
        }),
    )
    .unwrap();
    (format!("host_session={token}"), account)
}

#[test]
fn host_login_needs_only_consent_and_is_not_copied_into_reference_login() {
    let mut h = Harness::new();
    let (host_cookie, account) = host(&mut h);
    let state = h.create(None);
    let (mut reviewed, data, _) = review(&mut h, &state, &host_cookie);
    assert_eq!(data["human_id"], "alice");
    reviewed.cookie.push_str(&format!("; {host_cookie}"));
    h.app
        .store
        .atomic(|db, _| {
            let session = humangrant::human::browser(db, &reviewed.cookie)?;
            assert!(session.human_id.is_none());
            Ok(())
        })
        .unwrap();
    assert_eq!(h.approve(&reviewed).status, 200);
    let grants = h.browser("GET", "/human/grants", &reviewed.cookie, "", json!({}));
    assert_eq!(grants.status, 200);
    let grant_id = text(&page_data(&grants)["grants"][0], "grant_id");
    let csrf = text(&page_data(&grants), "csrf");
    *account.lock().unwrap() = None;
    assert_eq!(
        h.browser(
            "POST",
            &format!("/human/grants/{grant_id}/revoke"),
            &reviewed.cookie,
            &csrf,
            json!({})
        )
        .status,
        403
    );
    *account.lock().unwrap() = Some("alice".into());
    assert_eq!(
        h.browser(
            "POST",
            &format!("/human/grants/{grant_id}/revoke"),
            &reviewed.cookie,
            &csrf,
            json!({})
        )
        .status,
        200
    );
}

#[test]
fn host_account_switch_invalidates_displayed_confirmation() {
    let mut h = Harness::new();
    let (host_cookie, account) = host(&mut h);
    let state = h.create(None);
    let (mut reviewed, _, _) = review(&mut h, &state, &host_cookie);
    reviewed.cookie.push_str(&format!("; {host_cookie}"));
    *account.lock().unwrap() = Some("bob".into());
    let result = h.approve(&reviewed);
    assert_eq!(result.status, 403);
    assert_eq!(value(&result)["error"], "csrf_failed");
    assert_eq!(phase(&mut h, &state), "waiting_human");
    let (_, page, _) = review(&mut h, &state, &reviewed.cookie);
    assert_eq!(page["human_id"], "bob");
}

#[test]
fn expired_or_logged_out_host_login_cannot_fall_back_to_reference_cookie() {
    let mut h = Harness::new();
    let (_, _, reference) = h.authorized();
    let (host_cookie, account) = host(&mut h);
    let combined = format!("{}; {host_cookie}", reference.cookie);
    let state = h.create(None);
    let (reviewed, _, _) = review(&mut h, &state, &combined);
    *account.lock().unwrap() = None;
    assert_eq!(h.approve(&reviewed).status, 403);
    *account.lock().unwrap() = Some("alice".into());
    h.advance(301);
    assert_eq!(h.approve(&reviewed).status, 403);
    assert_eq!(phase(&mut h, &state), "waiting_human");
}
