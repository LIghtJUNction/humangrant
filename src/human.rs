use crate::auth::HumanAuthenticator;
use crate::config::Config;
use crate::crypto;
use crate::db::{self, RequestRecord, Store};
use crate::error::{Error, Result};
use crate::model::{Approval, Verification};
use crate::requests;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

pub struct Browser {
    pub token_hash: String,
    pub request_id: Option<String>,
    pub csrf: String,
    pub human_id: Option<String>,
    pub challenge: Option<String>,
    pub challenge_expires_at: Option<i64>,
    pub challenge_used: bool,
}

pub fn browser(db: &Connection, cookie: &str) -> Result<Browser> {
    let mut matching=cookie.split(';').map(str::trim).filter_map(|piece|piece.strip_prefix("hg_browser="));
    let token=matching.next().ok_or_else(Error::forbidden)?;
    if matching.next().is_some() || token.len()!=43 { return Err(Error::forbidden()); }
    let token_hash=crypto::hash(token.as_bytes());
    db.query_row("SELECT token_hash,request_id,csrf,human_id,challenge,challenge_expires_at,challenge_used
        FROM browser_sessions WHERE token_hash=?1 AND expires_at>hg_now()",params![token_hash],|r| Ok(Browser {
            token_hash:r.get(0)?,request_id:r.get(1)?,csrf:r.get(2)?,human_id:r.get(3)?,challenge:r.get(4)?,
            challenge_expires_at:r.get(5)?,challenge_used:r.get(6)?,
        })).optional()?.ok_or_else(Error::forbidden)
}

fn make_browser(db: &Connection, request_id: Option<&str>, human: Option<&str>, now: i64) -> Result<(String,String)> {
    let token=crypto::random_token();
    let csrf=crypto::random_token();
    db.execute("INSERT INTO browser_sessions(token_hash,request_id,csrf,human_id,expires_at) VALUES(?1,?2,?3,?4,?5)",
        params![crypto::hash(token.as_bytes()),request_id,csrf,human,now+1800])?;
    Ok((token,csrf))
}

pub fn cookie(config: &Config, token: &str) -> String {
    format!("hg_browser={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=1800{}",
        if config.public_origin.starts_with("https://") {"; Secure"} else {""})
}

pub fn csrf_check(session: &Browser, origin: &str, csrf: &str, config: &Config) -> Result<()> {
    if origin!=config.public_origin || csrf!=session.csrf {
        return Err(Error::new(403,"csrf_failed","A same-origin browser confirmation is required."));
    }
    Ok(())
}

pub fn authenticated_account(db: &Connection, session: &Browser) -> Result<String> {
    let human=session.human_id.as_ref().ok_or_else(Error::forbidden)?;
    let enabled: bool=db.query_row("SELECT EXISTS(SELECT 1 FROM accounts WHERE id=?1 AND enabled=1)",params![human],|r| r.get(0))?;
    if !enabled { return Err(Error::forbidden()); }
    Ok(human.clone())
}

fn same_request(session: &Browser, request: &RequestRecord) -> Result<()> {
    if session.request_id.as_deref()!=Some(request.id.as_str()) { return Err(Error::forbidden()); }
    Ok(())
}

pub fn page(store: &mut Store, config: &Config, link: &str, supplied_cookie: &str, source: &str) -> Result<(Value,Option<String>)> {
    store.atomic(|db,now| {
        let request=db::request_by_link(db,link)?;
        let old=browser(db,supplied_cookie).ok().filter(|session|session.request_id.as_deref()==Some(request.id.as_str()));
        let (session,new_cookie)=match old {
            Some(session)=>(session,None),
            None=> {
                let source=db::privacy_hash(db,source)?;
                db::check_rate(db,&[(format!("browser:{source}"),120),("browser:service".into(),1000)],now)?;
                let (token,_)=make_browser(db,Some(&request.id),None,now)?;
                (browser(db,&format!("hg_browser={token}"))?,Some(cookie(config,&token)))
            }
        };
        let human=authenticated_account(db,&session).ok();
        let mut grantable=vec![];
        if let Some(account)=&human {
            for permission in &request.permissions {
                if requests::human_permission(db,account,permission)? { grantable.push(permission.clone()); }
            }
        }
        Ok((json!({"view":"human","protocol_version":crate::model::PROTOCOL,"csrf":session.csrf,
            "origin":config.public_origin,"request_id":request.id,"link":link,"phase":request.phase,
            "actor_id":request.actor_id,"client_id":request.client_id,"target_service":request.target_service,
            "purpose":request.purpose,"requested_permissions":request.permissions,"grantable_permissions":grantable,
            "expected_human_id":request.expected_human_id,"human_id":human,"expires_at":request.expires_at,
            "requested_grant_expires_at":request.requested_grant_expires_at,"checked_at":now}),new_cookie))
    })
}

pub fn begin(store: &mut Store, config: &Config, link: &str, cookie: &str, origin: &str, csrf: &str, source: &str) -> Result<Value> {
    store.atomic(|db,now| {
        let request=db::request_by_link(db,link)?;
        db::require_open(&request,now)?;
        if request.phase=="approved" { return Err(Error::state()); }
        let session=browser(db,cookie)?;
        same_request(&session,&request)?;
        csrf_check(&session,origin,csrf,config)?;
        let source=db::privacy_hash(db,source)?;
        db::check_rate(db,&[(format!("human-begin:{source}"),60),("human-begin:service".into(),600)],now)?;
        let expires=(now+120).min(request.expires_at);
        let challenge=serde_json::to_string(&json!(["HumanGrant human authentication 0.1",config.public_origin,
            request.id,session.token_hash,crypto::random_token(),expires]))?;
        db.execute("UPDATE browser_sessions SET challenge=?1,challenge_expires_at=?2,challenge_used=0 WHERE token_hash=?3",
            params![challenge,expires,session.token_hash])?;
        if request.phase=="waiting_human" {
            db.execute("UPDATE requests SET phase='authenticating_human',status_updated_at=hg_now() WHERE id=?1",params![request.id])?;
        }
        Ok(json!({"challenge":challenge,"expires_at":expires,"message":"This verifies an account. It does not approve the request."}))
    })
}

pub struct BrowserWrite<'a> {
    pub link: &'a str, pub cookie: &'a str, pub origin: &'a str, pub csrf: &'a str,
}

pub fn verify(store: &mut Store, config: &Config, authenticator: &dyn HumanAuthenticator,
    browser_write: &BrowserWrite<'_>, input: &Verification) -> Result<(Value,String)>
{
    store.atomic(|db,now| {
        let request=db::request_by_link(db,browser_write.link)?;
        db::require_open(&request,now)?;
        if request.phase=="approved" { return Err(Error::state()); }
        let session=browser(db,browser_write.cookie)?;
        same_request(&session,&request)?;
        csrf_check(&session,browser_write.origin,browser_write.csrf,config)?;
        if session.challenge_used || session.challenge_expires_at.is_none_or(|expires|expires<=now) {
            return Err(Error::forbidden());
        }
        let challenge=session.challenge.as_ref().ok_or_else(Error::forbidden)?;
        let principal=authenticator.authenticate(db,&input.public_key,challenge,&input.signature)?;
        if request.expected_human_id.as_deref().is_some_and(|id|id!=principal.account_id) {
            return Err(Error::new(403,"expected_human_mismatch","This request requires a different account."));
        }
        let (token,csrf)=make_browser(db,Some(&request.id),Some(&principal.account_id),now)?;
        // Deleting the old session consumes its challenge and prevents session fixation.
        db.execute("DELETE FROM browser_sessions WHERE token_hash=?1",params![session.token_hash])?;
        if request.phase=="authenticating_human" {
            db.execute("UPDATE requests SET phase='awaiting_consent',status_updated_at=hg_now() WHERE id=?1",params![request.id])?;
        }
        Ok((json!({"status":"awaiting_consent","human_id":principal.account_id,"csrf":csrf}),cookie(config,&token)))
    })
}

pub fn decide(store: &mut Store, config: &Config, browser_write: &BrowserWrite<'_>, approval: Option<&Approval>) -> Result<Value> {
    store.atomic(|db,now| {
        let request=db::request_by_link(db,browser_write.link)?;
        db::require_open(&request,now)?;
        let session=browser(db,browser_write.cookie)?;
        same_request(&session,&request)?;
        csrf_check(&session,browser_write.origin,browser_write.csrf,config)?;
        let human=authenticated_account(db,&session)?;
        if request.expected_human_id.as_deref().is_some_and(|id|id!=human) {
            return Err(Error::new(403,"expected_human_mismatch","This request requires a different account."));
        }
        if let Some(approval)=approval { requests::approve(db,&request.id,&human,approval,now) }
        else {
            if request.phase!="awaiting_consent" { return Err(Error::state()); }
            db.execute("UPDATE requests SET phase='rejected',status_updated_at=hg_now() WHERE id=?1",params![request.id])?;
            Ok(json!({"status":"rejected"}))
        }
    })
}

pub fn grants_page(store: &mut Store, config: &Config, cookie: &str) -> Result<Value> {
    store.atomic(|db,_| {
        let session=browser(db,cookie)?;
        let human=authenticated_account(db,&session)?;
        Ok(json!({"view":"grants","origin":config.public_origin,"csrf":session.csrf,
            "human_id":human,"grants":requests::list_grants(db,&human)?["grants"]}))
    })
}

pub fn revoke(store: &mut Store, config: &Config, id: &str, cookie: &str, origin: &str, csrf: &str) -> Result<Value> {
    store.atomic(|db,_| {
        let session=browser(db,cookie)?;
        csrf_check(&session,origin,csrf,config)?;
        let human=authenticated_account(db,&session)?;
        requests::revoke(db,id,&human)
    })
}

pub fn invite_page(store: &mut Store, config: &Config, token: &str, supplied_cookie: &str, source: &str) -> Result<(Value,Option<String>)> {
    store.atomic(|db,now| {
        let request_id=db.query_row("SELECT request_id FROM mail_operations WHERE action_token=?1",params![token],|r| r.get::<_,String>(0))
            .optional()?.ok_or_else(Error::not_found)?;
        let old=browser(db,supplied_cookie).ok().filter(|s|s.request_id.as_deref()==Some(request_id.as_str()));
        let (session,new_cookie)=match old {
            Some(session)=>(session,None),
            None=> {
                let source=db::privacy_hash(db,source)?;
                db::check_rate(db,&[(format!("browser:{source}"),120),("browser:service".into(),1000)],now)?;
                let (new_token,_)=make_browser(db,Some(&request_id),None,now)?;
                (browser(db,&format!("hg_browser={new_token}"))?,Some(cookie(config,&new_token)))
            }
        };
        Ok((json!({"view":"invite","csrf":session.csrf,"token":token,"origin":config.public_origin}),new_cookie))
    })
}

pub fn refuse_mail(store: &mut Store, config: &Config, token: &str, cookie: &str, origin: &str, csrf: &str, block: bool) -> Result<Value> {
    store.atomic(|db,_| {
        let (request,recipient)=db.query_row("SELECT request_id,recipient_hash FROM mail_operations WHERE action_token=?1",
            params![token],|r| Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?))).optional()?.ok_or_else(Error::not_found)?;
        let session=browser(db,cookie)?;
        csrf_check(&session,origin,csrf,config)?;
        if session.request_id.as_deref()!=Some(request.as_str()) { return Err(Error::forbidden()); }
        if block {
            db.execute("INSERT OR IGNORE INTO mail_blocks(recipient_hash,created_at) VALUES(?1,hg_now())",params![recipient])?;
            db.execute("UPDATE mail_operations SET state='expired',transport_updated_at=hg_now() WHERE recipient_hash=?1 AND state='queued'",params![recipient])?;
        }
        // A mail capability can refuse an undecided request, never reverse completed human consent.
        db.execute("UPDATE requests SET phase='rejected',status_updated_at=hg_now() WHERE id=?1
            AND phase IN ('waiting_human','authenticating_human','awaiting_consent')",params![request])?;
        Ok(json!({"status":"recorded","message":"Your choice was recorded. Previously completed grants are unchanged."}))
    })
}
