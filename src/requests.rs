use crate::config::Config;
use crate::crypto::{self, Proof};
use crate::db::{self, Store};
use crate::error::{Error, Result};
use crate::model::{validate_permissions, Approval, CreateRequest, Permission, State};
use rusqlite::{named_params, params, Connection, OptionalExtension};
use serde_json::{json, Value};

pub fn create(
    store: &mut Store,
    config: &Config,
    proof: &Proof,
    input: &CreateRequest,
    source: &str,
) -> Result<State> {
    input.validate()?;
    if proof.authorization != "anonymous" {
        return Err(Error::forbidden());
    }
    let ttl = input
        .session_ttl_seconds
        .unwrap_or(config.grant_ttl_seconds);
    if !(60..=config.grant_ttl_seconds).contains(&ttl) {
        return Err(Error::invalid());
    }
    let id = crypto::random_token();
    let permissions = serde_json::to_string(&input.requested_permissions)?;
    store.atomic(|db,now| {
        let source=db::privacy_hash(db,source)?;
        db::check_rate(db,&[(format!("create:actor:{}",proof.actor_id),config.create_actor_per_hour),
            (format!("create:source:{source}"),config.create_source_per_hour),
            ("create:service".into(),config.create_service_per_hour)],now)?;
        let known: bool=db.query_row("SELECT EXISTS(SELECT 1 FROM clients WHERE id=?1 AND target_service=?2)",
            params![input.client_id,input.target_service],|r| r.get(0))?;
        if !known { return Err(Error::forbidden()); }
        db.execute(include_str!("sql/create_request.sql"),named_params! {
            ":id":id,":actor":proof.actor_id,":public_key":proof.public_key,
            ":client":input.client_id,":service":input.target_service,":purpose":input.purpose,
            ":permissions":permissions,":expected":input.expected_human_id,
            ":link":crypto::random_token(),":expires":now+config.request_ttl_seconds,
            ":grant_expires":now+ttl,":poll_interval":config.poll_interval_seconds,":audit":crypto::random_token(),
        })?;
        db::state_object(db,config,&db::request_record(db,&id)?,now)
    })
}

pub fn state(store: &mut Store, config: &Config, id: &str, actor: &str) -> Result<State> {
    // Commit the increased polling interval even when the HTTP result is 429.
    store.atomic(|db, now| {
        let mut request = db::own_request(db, id, actor)?;
        let terminal =
            ["succeeded", "rejected", "expired", "cancelled"].contains(&request.phase.as_str());
        if !terminal && now < request.next_poll_at {
            let interval = (request.poll_interval + 5).min(60);
            db.execute(
                "UPDATE requests SET poll_interval=?1,next_poll_at=?2 WHERE id=?3",
                params![interval, now + interval, id],
            )?;
            return Ok(Err(Error::slow_down(interval as u64)));
        }
        if !terminal {
            db.execute(
                "UPDATE requests SET next_poll_at=?1 WHERE id=?2",
                params![now + request.poll_interval, id],
            )?;
            request.next_poll_at = now + request.poll_interval;
        }
        Ok(db::state_object(db, config, &request, now))
    })?
}

pub fn cancel(store: &mut Store, id: &str, actor: &str) -> Result<Value> {
    store.atomic(|db, now| {
        let request = db::own_request(db, id, actor)?;
        if request.phase == "cancelled" {
            return Ok(json!({"status":"cancelled"}));
        }
        db::require_open(&request, now)?;
        db.execute(
            "UPDATE requests SET phase='cancelled',status_updated_at=hg_now() WHERE id=?1",
            params![id],
        )?;
        db.execute(
            "UPDATE grants SET revoked_at=hg_now() WHERE request_id=?1 AND revoked_at IS NULL",
            params![id],
        )?;
        Ok(json!({"status":"cancelled"}))
    })
}

pub fn approve(
    db: &Connection,
    id: &str,
    human: &str,
    input: &Approval,
    now: i64,
) -> Result<Value> {
    validate_permissions(&input.permissions)?;
    let request = db::request_record(db, id)?;
    db::require_open(&request, now)?;
    if request.phase != "awaiting_consent" {
        return Err(Error::state());
    }
    if request
        .expected_human_id
        .as_deref()
        .is_some_and(|expected| expected != human)
    {
        return Err(Error::new(
            403,
            "expected_human_mismatch",
            "This request requires a different account.",
        ));
    }
    if input.expires_at <= now || input.expires_at > request.requested_grant_expires_at {
        return Err(Error::forbidden());
    }
    for permission in &input.permissions {
        if !request.permissions.contains(permission) || !human_permission(db, human, permission)? {
            return Err(Error::forbidden());
        }
    }
    let id_grant = crypto::random_token();
    db.execute(
        include_str!("sql/approve.sql"),
        named_params! {
            ":id":id_grant,":request":id,":human":human,
            ":permissions":serde_json::to_string(&input.permissions)?,":expires":input.expires_at,
        },
    )?;
    Ok(json!({"status":"approved","grant_id":id_grant,"expires_at":input.expires_at}))
}

pub fn claim(store: &mut Store, id: &str, actor: &str) -> Result<Value> {
    store.atomic(|db,now| {
        let request=db::own_request(db,id,actor)?;
        if request.phase=="succeeded" {
            return Err(Error::new(409,"credential_already_issued","The credential was issued once. It cannot be recovered. Revoke the grant before requesting new access."));
        }
        db::require_open(&request,now)?;
        if request.phase!="approved" { return Err(Error::state()); }
        let grant=db.query_row("SELECT id,expires_at FROM grants WHERE request_id=?1 AND revoked_at IS NULL AND expires_at>hg_now()",
            params![id],|r| Ok((r.get::<_,String>(0)?,r.get::<_,i64>(1)?))).optional()?.ok_or_else(Error::forbidden)?;
        let token=crypto::random_token();
        let count=db.execute(include_str!("sql/claim.sql"),named_params! {
            ":id":crypto::random_token(),":request":id,":actor":actor,":token_hash":crypto::hash(token.as_bytes()),
        })?;
        if count!=1 { return Err(Error::forbidden()); }
        Ok(json!({"access_token":token,"token_type":"HumanGrant","grant_id":grant.0,"expires_at":grant.1}))
    })
}

pub fn human_permission(db: &Connection, human: &str, permission: &Permission) -> Result<bool> {
    Ok(db.query_row(
        "SELECT EXISTS(SELECT 1 FROM entitlements e JOIN accounts a ON a.id=e.account_id
        JOIN resources r ON r.target_service=e.target_service AND r.id=e.resource
        JOIN service_policy p ON p.target_service=e.target_service AND p.action=e.action
        WHERE a.enabled=1 AND e.account_id=?1 AND r.owner_id=?1 AND e.target_service='notes'
        AND e.action=?2 AND e.resource=?3)",
        params![human, permission.action, permission.resource],
        |r| r.get(0),
    )?)
}

pub fn list_grants(db: &Connection, human: &str) -> Result<Value> {
    let mut statement=db.prepare("SELECT id,request_id,actor_id,client_id,target_service,permissions,created_at,expires_at,revoked_at,audit_id
        FROM grants WHERE human_id=?1 ORDER BY created_at DESC,id")?;
    let rows = statement.query_map(params![human], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, String>(3)?,
            r.get::<_, String>(4)?,
            r.get::<_, String>(5)?,
            r.get::<_, i64>(6)?,
            r.get::<_, i64>(7)?,
            r.get::<_, Option<i64>>(8)?,
            r.get::<_, String>(9)?,
        ))
    })?;
    let mut grants = vec![];
    for row in rows {
        let (id, request, actor, client, service, permissions, created, expires, revoked, audit) =
            row?;
        grants.push(
            json!({"grant_id":id,"request_id":request,"grantor_id":human,"actor_id":actor,
            "public_key_id":actor,"client_id":client,"target_service":service,
            "permissions":serde_json::from_str::<Value>(&permissions)?,"created_at":created,
            "expires_at":expires,"revoked_at":revoked,"audit_id":audit}),
        );
    }
    Ok(json!({"grants":grants}))
}

pub fn revoke(db: &Connection, id: &str, human: &str) -> Result<Value> {
    let owner = db
        .query_row(
            "SELECT human_id FROM grants WHERE id=?1",
            params![id],
            |r| r.get::<_, String>(0),
        )
        .optional()?
        .ok_or_else(Error::not_found)?;
    if owner != human {
        return Err(Error::not_found());
    }
    db.execute(
        "UPDATE grants SET revoked_at=hg_now() WHERE id=?1 AND revoked_at IS NULL",
        params![id],
    )?;
    Ok(json!({"status":"revoked","grant_id":id}))
}

pub fn session_context(db: &Connection, proof: &Proof) -> Result<Value> {
    let token_hash = crypto::hash(proof.authorization.as_bytes());
    let grant = db
        .query_row(
            "SELECT g.id,g.human_id,g.client_id,g.target_service,g.expires_at,g.audit_id
        FROM sessions s JOIN grants g ON g.id=s.grant_id JOIN accounts a ON a.id=g.human_id
        JOIN clients c ON c.id=g.client_id AND c.target_service=g.target_service
        WHERE s.token_hash=?1 AND s.actor_id=?2 AND g.actor_id=?2 AND g.revoked_at IS NULL
        AND g.expires_at>hg_now() AND a.enabled=1",
            params![token_hash, proof.actor_id],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, i64>(4)?,
                    r.get::<_, String>(5)?,
                ))
            },
        )
        .optional()?
        .ok_or_else(|| Error::new(401, "invalid_session", "This AI session is not valid."))?;
    let permissions = effective_permissions(db, &token_hash, &proof.actor_id, &grant.3)?;
    Ok(
        json!({"actor":{"kind":"ai","id":proof.actor_id},"grantor_id":grant.1,"grant_id":grant.0,
        "client_id":grant.2,"target_service":grant.3,"expires_at":grant.4,"audit_id":grant.5,
        "effective_permissions":permissions}),
    )
}

pub fn effective_permissions(
    db: &Connection,
    token_hash: &str,
    actor: &str,
    service: &str,
) -> Result<Vec<Permission>> {
    let mut statement = db.prepare(include_str!("sql/effective_permissions.sql"))?;
    let rows = statement.query_map(
        named_params! {":token_hash":token_hash,":actor":actor,":service":service},
        |r| {
            Ok(Permission {
                action: r.get(0)?,
                resource: r.get(1)?,
            })
        },
    )?;
    let mut permissions = vec![];
    for row in rows {
        permissions.push(row?);
    }
    Ok(permissions)
}

pub fn note(
    store: &mut Store,
    proof: &Proof,
    resource: &str,
    content: Option<&str>,
) -> Result<Value> {
    let permission = Permission {
        action: if content.is_some() {
            "notes.write"
        } else {
            "notes.read"
        }
        .into(),
        resource: resource.into(),
    };
    permission.validate()?;
    if content.is_some_and(|text| text.len() > 16_384) {
        return Err(Error::invalid());
    }
    store.atomic(|db, _| {
        let context = if proof.authorization == "anonymous" {
            let human = db::registered_human(db, &proof.actor_id)?;
            if !human_permission(db, &human, &permission)? {
                return Err(Error::forbidden());
            }
            json!({"actor":{"kind":"human","id":human},"grantor_id":human,"target_service":"notes"})
        } else {
            let context = session_context(db, proof)?;
            let effective: Vec<Permission> =
                serde_json::from_value(context["effective_permissions"].clone())?;
            if !effective.contains(&permission) {
                return Err(Error::forbidden());
            }
            context
        };
        if let Some(text) = content {
            db.execute(
                "UPDATE resources SET content=?1 WHERE target_service='notes' AND id=?2",
                params![text, resource],
            )?;
        }
        let text: String = db.query_row(
            "SELECT content FROM resources WHERE target_service='notes' AND id=?1",
            params![resource],
            |r| r.get(0),
        )?;
        Ok(json!({"context":context,"resource":{"id":resource,"content":text}}))
    })
}
