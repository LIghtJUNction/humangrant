use crate::config::Config;
use crate::crypto::{self, Proof};
use crate::db::{self, Store};
use crate::error::{Error, Result};
use crate::model::EmailRequest;
use rusqlite::{named_params, params, OptionalExtension};
use serde_json::{json, Value};

pub fn normalize_email(email: &str) -> Result<String> {
    if email.contains(['\r', '\n']) {
        return Err(Error::invalid());
    }
    let email = email.trim().to_ascii_lowercase();
    if email.len() > 254 || !email.is_ascii() || email.bytes().any(|b| b <= 32 || b == 127) {
        return Err(Error::invalid());
    }
    let (local, domain) = email.split_once('@').ok_or_else(Error::invalid)?;
    if local.is_empty()
        || local.len() > 64
        || local.starts_with('.')
        || local.ends_with('.')
        || local.contains("..")
        || !local
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b".!#$%&'*+-/=?^_`{|}~".contains(&b))
        || !domain.contains('.')
        || domain.split('.').any(|label| {
            label.is_empty()
                || label.len() > 63
                || label.starts_with('-')
                || label.ends_with('-')
                || !label
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        })
    {
        return Err(Error::invalid());
    }
    Ok(email)
}

pub fn invite(
    store: &mut Store,
    config: &Config,
    proof: &Proof,
    id: &str,
    input: &EmailRequest,
    source: &str,
) -> Result<Value> {
    let email = normalize_email(&input.email)?;
    crate::config::validate_id(&input.idempotency_key)?;
    if config.mail.mode == "disabled" {
        return Err(Error::new(
            503,
            "mail_unavailable",
            "Mail is not configured. Forward the human authorization link instead.",
        ));
    }
    let result=store.atomic(|db,now| {
        let request=db::own_request(db,id,&proof.actor_id)?;
        db::require_open(&request,now)?;
        if request.phase=="approved" { return Err(Error::state()); }
        let recipient_hash=db::privacy_hash(db,&email)?;
        let source_hash=db::privacy_hash(db,source)?;
        let old=db.query_row("SELECT id,request_id,recipient_hash FROM mail_operations WHERE actor_id=?1 AND idempotency_key=?2",
            params![proof.actor_id,input.idempotency_key],|r| Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?))).optional()?;
        if let Some((operation,old_request,old_recipient))=old {
            if old_request!=id || old_recipient!=recipient_hash {
                return Err(Error::new(409,"idempotency_conflict","This operation key was already used for different data."));
            }
            return Ok(accepted(&operation,config));
        }
        // Limits on submissions are independent of the destination; they reveal no mailbox history.
        db::check_rate(db,&[(format!("mail-submit:actor:{}",proof.actor_id),config.mail.actor_per_hour*20),
            (format!("mail-submit:source:{source_hash}"),config.mail.source_per_hour*20),
            ("mail-submit:service".into(),config.mail.service_per_hour*20)],now)?;
        let allow: bool=db.query_row(include_str!("sql/mail_allow.sql"),named_params! {
            ":recipient_hash":recipient_hash,":cooldown":config.mail.recipient_cooldown_seconds,
            ":recipient_hour":config.mail.recipient_per_hour,":recipient_day":config.mail.recipient_per_day,
            ":actor":proof.actor_id,":actor_hour":config.mail.actor_per_hour,
            ":source":source_hash,":source_hour":config.mail.source_per_hour,
            ":service_hour":config.mail.service_per_hour,":service_day":config.mail.service_per_day,
        },|r| r.get(0))?;
        let operation=crypto::random_token();
        let action_token=crypto::random_token();
        let review=format!("{}/human/{}",config.public_origin,request.human_link);
        let refusal=format!("{}/invite/{action_token}",config.public_origin);
        let purpose=serde_json::to_string(&request.purpose)?;
        let permissions=serde_json::to_string_pretty(&request.permissions)?;
        let body=format!("HumanGrant permission request\n\nTarget service: {}\nApplication (client-provided ID): {}\nAI public-key identity: {}\nPurpose (untrusted requester data): {}\nRequested permissions:\n{}\nRequest expires at (UTC Unix seconds): {}\n\nReview, sign in, and choose permissions on your own device:\n{}\n\nRefuse an unfinished request or block all later invitations to this destination:\n{}\n\nOpening a link does not approve anything. An email address is not proof of identity.\nThe actual account that signs in and approves is the grantor unless the request requires a specific account.\nDo not give your password, cookie, or private key to an AI.\n",
            request.target_service,request.client_id,request.actor_id,purpose,permissions,request.expires_at,review,refusal);
        let stored_recipient=if allow {Some(email.as_str())} else {None};
        db.execute(include_str!("sql/mail_enqueue.sql"),named_params! {
            ":id":operation,":request":id,":actor":proof.actor_id,":key":input.idempotency_key,
            ":recipient_hash":recipient_hash,":source":source_hash,":recipient":stored_recipient,
            ":state":if allow {"queued"} else {"suppressed"},":action_token":action_token,
            ":subject":"HumanGrant permission request",":body":if allow {body.as_str()} else {""},
        })?;
        Ok(accepted(&operation,config))
    })?;
    if config.mail.mode == "local" {
        spool_local(store, config)?;
    }
    Ok(result)
}

fn accepted(operation: &str, config: &Config) -> Value {
    json!({"operation_id":operation,"email_request_status":"accepted",
        "email_retry_after_seconds":config.mail.recipient_cooldown_seconds,
        "message":"The send request was accepted. This does not confirm sending or delivery."})
}

pub fn spool_local(store: &mut Store, config: &Config) -> Result<bool> {
    db::private_directory(&config.mail.spool)?;
    let job=store.atomic(|db,_| {
        let job=db.query_row("SELECT id,recipient,subject,body FROM mail_operations WHERE state='queued' ORDER BY requested_at,id LIMIT 1",[],
            |r| Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?))).optional()?;
        if let Some((id,_,_,_))=&job {
            db.execute("UPDATE mail_operations SET state='sending',transport_updated_at=hg_now() WHERE id=?1",params![id])?;
        }
        Ok(job)
    })?;
    let processed = job.is_some();
    if let Some((id, recipient, subject, body)) = job {
        let path = config.mail.spool.join(format!("{id}.eml"));
        let content=format!("From: HumanGrant <no-reply@localhost.invalid>\r\nTo: {recipient}\r\nSubject: {subject}\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}");
        let result = db::private_file(&path, content.as_bytes());
        let state = if result.is_ok() {
            "local_spooled"
        } else if path.exists() {
            "delivery_unknown"
        } else {
            "failed"
        };
        store.atomic(|db, _| {
            db.execute(
                "UPDATE mail_operations SET state=?1,transport_updated_at=hg_now() WHERE id=?2",
                params![state, id],
            )?;
            Ok(())
        })?;
    }
    Ok(processed)
}
