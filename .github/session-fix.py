from pathlib import Path

ROOT = Path.cwd()
def replace(path, old, new, count=1):
    p=ROOT/path
    content=p.read_text(encoding='utf-8')
    if content.count(old) != count:
        raise ValueError(f'{path}: expected {count} matches; found {content.count(old)}')
    p.write_text(content.replace(old,new),encoding='utf-8')

def write(path, content):
    p=ROOT/path
    if p.exists(): raise ValueError(f'{path} already exists')
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(content,encoding='utf-8')

replace('src/auth.rs', 'pub trait HumanAuthenticator: Send + Sync {\n', '''pub trait HumanAuthenticator: Send + Sync {
    /// Resolve the current browser login on every review and decision.
    /// Hosts override this with their real session validator, including expiry and logout.
    /// Return None for no valid login; never use a caller-supplied account ID as proof.
    /// An override is authoritative: the caller does not fall back to a reference login.
    fn session_principal(
        &self,
        db: &Connection,
        cookie: &str,
        _now: i64,
    ) -> Result<Option<HumanPrincipal>> {
        match crate::human::browser(db, cookie)
            .and_then(|session| crate::human::authenticated_account(db, &session))
        {
            Ok(account_id) => Ok(Some(HumanPrincipal { account_id })),
            Err(error) if error.status == 403 => Ok(None),
            Err(error) => Err(error),
        }
    }

''')
replace('src/crypto.rs', 'pub fn public_key(encoded: &str) -> Result<VerifyingKey> {', '''pub fn private_hash_matches(secret: &[u8], value: &str, tag: &str) -> Result<bool> {
    let Ok(tag) = URL_SAFE_NO_PAD.decode(tag) else {
        return Ok(false);
    };
    let mut mac = Hmac::<Sha256>::new_from_slice(secret).map_err(|_| Error::internal())?;
    mac.update(value.as_bytes());
    Ok(mac.verify_slice(&tag).is_ok())
}

pub fn public_key(encoded: &str) -> Result<VerifyingKey> {''')
replace('src/human.rs', 'SameSite=Strict', 'SameSite=Lax')
replace('src/human.rs', 'fn same_request(session: &Browser, request: &RequestRecord) -> Result<()> {', '''fn current_account(
    db: &Connection,
    authenticator: &dyn HumanAuthenticator,
    cookie: &str,
    now: i64,
) -> Result<Option<String>> {
    let Some(principal) = authenticator.session_principal(db, cookie, now)? else {
        return Ok(None);
    };
    let enabled: bool = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM accounts WHERE id=?1 AND enabled=1)",
        params![principal.account_id],
        |row| row.get(0),
    )?;
    Ok(enabled.then_some(principal.account_id))
}

fn action_message(scope: [&str; 3]) -> Result<String> {
    Ok(serde_json::to_string(&json!(["HumanGrant browser action 0.1", scope]))?)
}

fn action_csrf(session: &Browser, scope: [&str; 3]) -> Result<String> {
    crypto::private_hash(session.csrf.as_bytes(), &action_message(scope)?)
}

fn check_action(
    session: &Browser,
    origin: &str,
    csrf: &str,
    config: &Config,
    scope: [&str; 3],
) -> Result<()> {
    if origin != config.public_origin
        || !crypto::private_hash_matches(session.csrf.as_bytes(), &action_message(scope)?, csrf)?
    {
        return Err(Error::new(403, "csrf_failed", "Reload this page and confirm the displayed account and request."));
    }
    Ok(())
}

fn same_request(session: &Browser, request: &RequestRecord) -> Result<()> {''')
replace('src/human.rs', '''pub fn page(
    store: &mut Store,
    config: &Config,
''', '''pub fn page(
    store: &mut Store,
    config: &Config,
    authenticator: &dyn HumanAuthenticator,
''')
replace('src/human.rs', '''        let old=browser(db,supplied_cookie).ok().filter(|session|session.request_id.as_deref()==Some(request.id.as_str()));''', '''        let human=current_account(db,authenticator,supplied_cookie,now)?;
        // Reuse the login without rebinding it to a request or extending its lifetime.
        let old=browser(db,supplied_cookie).ok().filter(|session|human.is_some() || session.request_id.as_deref()==Some(request.id.as_str()));''')
replace('src/human.rs', '''        let human=authenticated_account(db,&session).ok();
        let mut grantable=vec![];''', '''        let csrf=match &human {
            Some(account)=>action_csrf(&session,["consent",&request.id,account])?,
            None=>session.csrf.clone(),
        };
        let mut grantable=vec![];''')
replace('src/human.rs', '''"protocol_version":crate::model::PROTOCOL,"csrf":session.csrf,''', '''"protocol_version":crate::model::PROTOCOL,"csrf":csrf,''')
replace('src/human.rs', '''        Ok((json!({"status":"awaiting_consent","human_id":principal.account_id,"csrf":csrf}),cookie(config,&token)))''', '''        let session=browser(db,&format!("hg_browser={token}"))?;
        let csrf=action_csrf(&session,["consent",&request.id,&principal.account_id])?;
        Ok((json!({"status":"awaiting_consent","human_id":principal.account_id,"csrf":csrf}),cookie(config,&token)))''')
replace('src/human.rs', '''let (token,csrf)=make_browser(db,Some(&request.id),Some(&principal.account_id),now)?;''', '''let (token,_)=make_browser(db,Some(&request.id),Some(&principal.account_id),now)?;''')
replace('src/human.rs', '''pub fn decide(
    store: &mut Store,
    config: &Config,
''', '''pub fn decide(
    store: &mut Store,
    config: &Config,
    authenticator: &dyn HumanAuthenticator,
''')
replace('src/human.rs', '''        same_request(&session, &request)?;
        csrf_check(&session, browser_write.origin, browser_write.csrf, config)?;
        let human = authenticated_account(db, &session)?;''', '''        let human = current_account(db, authenticator, browser_write.cookie, now)?
            .ok_or_else(Error::forbidden)?;
        check_action(&session, browser_write.origin, browser_write.csrf, config,
            ["consent", &request.id, &human])?;''')
replace('src/human.rs', '''        if let Some(approval) = approval {
            requests::approve(db, &request.id, &human, approval, now)
        } else {
            if request.phase != "awaiting_consent" {
                return Err(Error::state());
            }''', '''        if !["waiting_human", "authenticating_human", "awaiting_consent"].contains(&request.phase.as_str()) {
            return Err(Error::state());
        }
        // A protected, explicit decision may skip a new login. A GET never advances consent.
        db.execute("UPDATE requests SET phase='awaiting_consent',status_updated_at=hg_now()
            WHERE id=?1 AND phase IN ('waiting_human','authenticating_human')", params![request.id])?;
        if let Some(approval) = approval {
            requests::approve(db, &request.id, &human, approval, now)
        } else {''')
replace('src/human.rs', '''pub fn grants_page(store: &mut Store, config: &Config, cookie: &str) -> Result<Value> {
    store.atomic(|db, _| {
        let session = browser(db, cookie)?;
        let human = authenticated_account(db, &session)?;''', '''pub fn grants_page(store: &mut Store, config: &Config, authenticator: &dyn HumanAuthenticator, cookie: &str) -> Result<Value> {
    store.atomic(|db, now| {
        let session = browser(db, cookie)?;
        let human = current_account(db, authenticator, cookie, now)?.ok_or_else(Error::forbidden)?;
        let csrf = action_csrf(&session, ["grants", "", &human])?;''')
replace('src/human.rs', '''"view":"grants","origin":config.public_origin,"csrf":session.csrf,''', '''"view":"grants","origin":config.public_origin,"csrf":csrf,''')
replace('src/human.rs', '''pub fn revoke(
    store: &mut Store,
    config: &Config,
    id: &str,
    cookie: &str,
    origin: &str,
    csrf: &str,
) -> Result<Value> {
    store.atomic(|db, _| {
        let session = browser(db, cookie)?;
        csrf_check(&session, origin, csrf, config)?;
        let human = authenticated_account(db, &session)?;
        requests::revoke(db, id, &human)
    })
}''', '''pub fn revoke(
    store: &mut Store,
    config: &Config,
    authenticator: &dyn HumanAuthenticator,
    id: &str,
    write: &BrowserWrite<'_>,
) -> Result<Value> {
    store.atomic(|db, now| {
        let session = browser(db, write.cookie)?;
        let human = current_account(db, authenticator, write.cookie, now)?.ok_or_else(Error::forbidden)?;
        check_action(&session, write.origin, write.csrf, config, ["grants", "", &human])?;
        requests::revoke(db, id, &human)
    })
}''')
replace('src/human.rs', '''let old=browser(db,supplied_cookie).ok().filter(|s|s.request_id.as_deref()==Some(request_id.as_str()));''', '''let old=browser(db,supplied_cookie).ok();''')
replace('src/human.rs', '''Ok((json!({"view":"invite","csrf":session.csrf,"token":token,"origin":config.public_origin}),new_cookie))''', '''Ok((json!({"view":"invite","csrf":action_csrf(&session,["invite",token,""] )?,"token":token,"origin":config.public_origin}),new_cookie))''')
replace('src/human.rs', '''        csrf_check(&session,origin,csrf,config)?;
        if session.request_id.as_deref()!=Some(request.as_str()) { return Err(Error::forbidden()); }''', '''        check_action(&session,origin,csrf,config,["invite",token,""])?;''')
replace('src/web.rs', '''human::grants_page(&mut self.store, &self.config, cookie)?''', '''human::grants_page(&mut self.store, &self.config, self.authenticator.as_ref(), cookie)?''')
replace('src/web.rs', '''human::revoke(&mut self.store, &self.config, id, cookie, origin, csrf)?''', '''human::revoke(&mut self.store, &self.config, self.authenticator.as_ref(), id,
                        &BrowserWrite { link: "", cookie, origin, csrf })?''')
replace('src/web.rs', '''human::page(&mut self.store, &self.config, link, cookie, &request.source)?''', '''human::page(&mut self.store, &self.config, self.authenticator.as_ref(), link, cookie, &request.source)?''')
replace('src/web.rs', '''human::decide(&mut self.store, &self.config, &write, Some(&input))?''', '''human::decide(&mut self.store, &self.config, self.authenticator.as_ref(), &write, Some(&input))?''')
replace('src/web.rs', '''human::decide(&mut self.store, &self.config, &write, None)?''', '''human::decide(&mut self.store, &self.config, self.authenticator.as_ref(), &write, None)?''')
initial=(ROOT/'migrations/0001.sql').read_text()
trigger=initial.split('CREATE TRIGGER IF NOT EXISTS request_immutable',1)[1].split('\nEND;',1)[0]
trigger='CREATE TRIGGER request_immutable'+trigger+'\nEND;\n'
trigger=trigger.replace("(OLD.phase='waiting_human' AND NEW.phase IN ('authenticating_human','rejected','cancelled','expired'))", "(OLD.phase='waiting_human' AND NEW.phase IN ('authenticating_human','awaiting_consent','rejected','cancelled','expired'))")
write('migrations/0002_existing_login.sql', 'BEGIN IMMEDIATE;\nDROP TRIGGER request_immutable;\n'+trigger+'PRAGMA user_version=2;\nCOMMIT;\n')
replace('src/db.rs', '''} else if version != 1 {''', '''} else if version != 1 && version != 2 {''')
replace('src/db.rs', '''        let mut store = Self {
''', '''        if version < 2 {
            connection.execute_batch(include_str!("../migrations/0002_existing_login.sql"))?;
        }
        let mut store = Self {
''')
replace('tests/sql_harness.py', '''    db.executescript((ROOT / "migrations/0001.sql").read_text())''', '''    db.executescript((ROOT / "migrations/0001.sql").read_text())
    db.executescript((ROOT / "migrations/0002_existing_login.sql").read_text())''')
replace('tests/test_sql.py', '''@pytest.mark.parametrize("target", ["approved", "succeeded", "awaiting_consent"])''', '''@pytest.mark.parametrize("target", ["approved", "succeeded"])''')
replace('tests/protocol.rs', '''    let (state, issued, browser) = h.authorized();
    let revoke = h.browser(''', '''    let (state, issued, mut browser) = h.authorized();
    let grants = h.browser("GET", "/human/grants", &browser.cookie, "", json!({}));
    browser.csrf = text(&page_data(&grants), "csrf");
    let revoke = h.browser(''')
replace('examples/web/ui.js', '''app.append(element("span",data.phase.replaceAll("_"," "),"badge")); requestMetadata();''', '''app.append(element("span",data.human_id && ["waiting_human","authenticating_human","awaiting_consent"].includes(data.phase) ? "Ready for your decision" : data.phase.replaceAll("_"," "),"badge")); requestMetadata();''')
replace('examples/web/ui.js', '''  app.append(element("p",`Authenticated account: ${data.human_id}. Signing in did not approve this request.` ,"notice"));''', '''  if (data.expected_human_id && data.expected_human_id !== data.human_id) {
    app.append(element("p",`Signed in as ${data.human_id}. This request requires ${data.expected_human_id}. Switch accounts in this site's login, then reopen this link.`,"notice"));
    return;
  }
  app.append(element("p",`Signed in as ${data.human_id}. Choose the access to approve; no new login is needed.` ,"notice"));''')
replace('scripts/e2e.py', '''                mail_human=Human(origin,alice_key);mail_human.open(path)
                assert mail_human.authenticate(path)[0]==200''', '''                mail_human=human
                reviewed=mail_human.open(path)
                assert reviewed['human_id']=='alice' and reviewed['phase']=='waiting_human'
                assert client.state(request)['phase']=='waiting_human'
                expect_error(lambda:client.request('POST',f'/v1/requests/{request}/claim'),409)''')
replace('scripts/e2e.py', '''checks.append('local .eml invitation + idempotency + real consent + restricted read')''', '''checks.append('local .eml invitation + existing login without reauthentication + explicit consent + restricted read')''')
replace('spec/v0.1.md', '''| waiting_human | waiting | 等待人类中 | authenticating_human, rejected, cancelled, expired |''', '''| waiting_human | waiting | 等待人类中 | authenticating_human, awaiting_consent, rejected, cancelled, expired |''')
replace('spec/v0.1.md', 'a SameSite=Strict/HttpOnly session cookie', 'a SameSite=Lax/HttpOnly session cookie')
replace('SECURITY.md', 'SameSite=Strict/HttpOnly cookie', 'SameSite=Lax/HttpOnly cookie')
replace('openapi.yaml', 'HttpOnly, SameSite=Strict, Secure with HTTPS; independent of AI credentials.', 'HttpOnly, SameSite=Lax, Secure with HTTPS; independent of AI credentials. A valid existing human login skips reauthentication, not consent.')
replace('skills/humangrant-integrate/SKILL.md', '''4. Reuse server-verified human identity. Show actor key, service, actions, resources, expiry, and the actual grantor. Require a separate explicit consent decision.''', '''4. Check the existing server-verified login first: valid login → permission confirmation; no valid login → the site's login → confirmation. Do not require a logged-in user to authenticate again. Show actor key, service, actions, resources, expiry, and the actual grantor. Require explicit consent and recheck the login at submission.''')
replace('docs/integration.md', '''This interface is not a claim that existing browser sessions for every host can be attached unchanged.''', '''For an existing browser login, override `HumanAuthenticator::session_principal(db, cookie, now)`.
It is called on review, consent, grant listing and revocation. Validate the host's actual session,
expiry, logout and current account, then return its principal; return `None` for no valid login.
The override is authoritative and does not fall back to a reference cookie. The account must be
mapped to the host's current permission records. Do not copy a host identity into a long-lived
reference session. The default implementation checks the reference's public-key-verified login.''')
replace('spec/v0.1.md', '''## 5. Request signatures (strict profile)''', '''### Existing human login

A valid, server-verified login MUST lead directly to the permission confirmation view. Only a
missing, expired or invalid login requires authentication. Integrations MUST use the host's actual
session validator, not a posted account ID or an agent's assertion. The reference uses
`HumanAuthenticator::session_principal`; the host override is rechecked on every human operation.

An authenticated GET can display the account and choices, but MUST NOT advance the request phase,
approve access or create an AI session. The explicit approve/reject POST revalidates the login and
expected account, then enters `awaiting_consent` and applies the decision in one transaction.
No extra user click or authentication challenge is needed for this internal transition.
An invalid decision rolls back the transition. Request status remains distinct from page readiness.

Consent CSRF tokens are HMAC-SHA256 over the UTF-8 JSON array
`["HumanGrant browser action 0.1", ["consent", request_id, account_id]]`, keyed by the browser
session's server-side CSRF secret. They bind this browser, the displayed account and the immutable
request. Tokens for grant management and mail preferences use separate contexts. Switching account
or request invalidates the old confirmation. All POSTs still require the exact trusted Origin.
The reference cookie uses SameSite=Lax so a normal top-level link from email can carry an existing
login; cross-site submissions do not gain permission. Opening links does not extend the login's
30-minute server-side expiry. Integration hosts keep their own login lifetime and cookie policy.

## 5. Request signatures (strict profile)''')
replace('skills/humangrant-integrate/references/integration.md', '''current policy. Never expose arbitrary account IDs as a public authentication method.''', '''current policy. Never expose arbitrary account IDs as a public authentication method.
Check an existing login through `HumanAuthenticator::session_principal(db, cookie, now)` or the
host's equivalent server-side session API. A valid login skips identity verification and shows
permission confirmation immediately. Check the same account again when consent is submitted.
Do not copy the login lifetime, cache a logged-out principal, or treat opening a link as consent.
Test a second request with the same browser, an expired login, an account switch, and GET scanning.''')
replace('docs/integration.md', '''permissions, current human account and expiry. All choices start unchecked; approval is a separate POST.''', '''permissions, current human account and expiry. All choices start unchecked; approval is a separate POST.
A logged-in visitor sees these choices immediately, including on a new request. Reuse does not
extend the login lifetime. A changed or expired account must not submit the old confirmation.''')
for path, old, new in [
    ('README.md', 'You open it on your device and choose the actions and resources it can use.', 'You open it on your device and choose the actions and resources it can use. Already signed in? Go straight to approval.'),
    ('README.zh-CN.md', '你在自己的设备上打开，选择允许的操作和资源。', '你在自己的设备上打开，选择允许的操作和资源。已登录时，直接确认授权，无需重复登录。'),
]:
    if (ROOT/path).exists() and old in (ROOT/path).read_text():
        replace(path,old,new)
replace('clients/smtp_worker.py', "db.execute('PRAGMA user_version').fetchone()[0] != 1", "db.execute('PRAGMA user_version').fetchone()[0] not in (1, 2)")
replace('tests/sql_harness.py', 'def initialize(db: sqlite3.Connection) -> None:', 'def initialize(db: sqlite3.Connection, *, existing_login: bool = True) -> None:')
replace('tests/sql_harness.py', '    db.executescript((ROOT / "migrations/0002_existing_login.sql").read_text())', '    if existing_login:\n        db.executescript((ROOT / "migrations/0002_existing_login.sql").read_text())')
p=ROOT/'tests/protocol.rs'
p.write_text(p.read_text()+'\n#[path = "cases/existing_login.rs"]\nmod existing_login;\n')
