use crate::config::Config;
use crate::crypto;
use crate::error::{Error, Result};
use crate::model::{display_state, Permission, State, PROTOCOL};
use rusqlite::{
    functions::FunctionFlags, params, Connection, OptionalExtension, TransactionBehavior,
};
use std::sync::{
    atomic::{AtomicI64, Ordering},
    Arc,
};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub trait Clock: Send + Sync {
    fn now(&self) -> i64;
}
pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> i64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs() as i64
    }
}

pub struct Store {
    connection: Connection,
    clock: Arc<dyn Clock>,
    transaction_time: Arc<AtomicI64>,
}

impl Store {
    pub fn open(config: &Config, clock: Arc<dyn Clock>) -> Result<Self> {
        if let Some(parent) = config.database.parent() {
            if !parent.as_os_str().is_empty() {
                private_directory(parent)?;
            }
        }
        if !config.database.exists() {
            private_file(&config.database, b"")?;
        }
        let connection = Connection::open(&config.database)?;
        connection.busy_timeout(Duration::from_secs(5))?;
        connection.execute_batch(
            "PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;",
        )?;
        let transaction_time = Arc::new(AtomicI64::new(clock.now()));
        let sql_time = transaction_time.clone();
        connection.create_scalar_function("hg_now", 0, FunctionFlags::SQLITE_UTF8, move |_| {
            Ok(sql_time.load(Ordering::SeqCst))
        })?;
        let version: i64 = connection.query_row("PRAGMA user_version", [], |r| r.get(0))?;
        if version == 0 {
            let tables: i64=connection.query_row("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",[],|r| r.get(0))?;
            if tables != 0 {
                return Err(Error::new(
                    400,
                    "invalid_database",
                    "Refusing to replace an existing, unrecognized database.",
                ));
            }
            connection.execute_batch(include_str!("../migrations/0001.sql"))?;
        } else if version != 1 {
            return Err(Error::new(
                400,
                "invalid_database",
                "This database version is not supported.",
            ));
        }
        let mut store = Self {
            connection,
            clock,
            transaction_time,
        };
        store.atomic(|db,_| {
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('privacy_key',?1)",params![crypto::random_token()])?;
            let initialized: bool=db.query_row("SELECT EXISTS(SELECT 1 FROM settings WHERE key='bootstrap_complete')",[],|r| r.get(0))?;
            if !initialized {
                for account in &config.accounts {
                    db.execute("INSERT INTO accounts(id,key_id,public_key) VALUES(?1,?2,?3)",
                        params![account.id,crypto::key_id(&account.public_key)?,account.public_key])?;
                }
                for client in &config.client_ids {
                    db.execute("INSERT INTO clients(id,target_service) VALUES(?1,'notes')",params![client])?;
                }
                for action in ["notes.read","notes.write"] {
                    db.execute("INSERT INTO service_policy(target_service,action) VALUES('notes',?1)",params![action])?;
                }
                for resource in &config.resources {
                    db.execute("INSERT INTO resources(target_service,id,owner_id,content) VALUES('notes',?1,?2,?3)",
                        params![resource.id,resource.owner_id,resource.content])?;
                    for action in &resource.permissions {
                        db.execute("INSERT INTO entitlements(account_id,target_service,action,resource) VALUES(?1,'notes',?2,?3)",
                            params![resource.owner_id,action,resource.id])?;
                    }
                }
                db.execute("INSERT INTO settings(key,value) VALUES('bootstrap_complete','1')",[])?;
            }
            Ok(())
        })?;
        Ok(store)
    }

    pub fn now(&self) -> i64 {
        self.clock.now()
    }

    /// Trusted server integration boundary; not available over HTTP.
    /// The same lock covers authority checks and the protected database operation.
    pub fn atomic<T>(
        &mut self,
        operation: impl FnOnce(&Connection, i64) -> Result<T>,
    ) -> Result<T> {
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let now = self.clock.now();
        self.transaction_time.store(now, Ordering::SeqCst);
        transaction.execute_batch(include_str!("sql/expire.sql"))?;
        let result = operation(&transaction, now)?;
        transaction.commit()?;
        Ok(result)
    }

    pub fn reserve_nonce(&mut self, proof: &crypto::Proof) -> Result<()> {
        self.atomic(|db, now| {
            if proof.expires_at <= now {
                return Err(crypto::bad_signature());
            }
            let rows = db.execute(
                "INSERT OR IGNORE INTO nonces(key_id,nonce,expires_at) VALUES(?1,?2,?3)",
                params![proof.actor_id, proof.nonce, proof.expires_at],
            )?;
            if rows != 1 {
                return Err(Error::new(
                    401,
                    "signature_replay",
                    "This signed request has already been used.",
                ));
            }
            Ok(())
        })
    }

    pub fn remove_entitlement(
        &mut self,
        account: &str,
        action: &str,
        resource: &str,
    ) -> Result<()> {
        self.atomic(|db,now| {
            db.execute("DELETE FROM entitlements WHERE account_id=?1 AND target_service='notes' AND action=?2 AND resource=?3",
                params![account,action,resource])?;
            db.execute("INSERT INTO audit(audit_id,event,human_id,occurred_at) VALUES(?1,'permission_removed',?2,?3)",
                params![crypto::random_token(),account,now])?;
            Ok(())
        })
    }

    pub fn disable_account(&mut self, account: &str) -> Result<()> {
        self.atomic(|db,now| {
            db.execute("UPDATE accounts SET enabled=0 WHERE id=?1",params![account])?;
            db.execute("INSERT INTO audit(audit_id,event,human_id,occurred_at) VALUES(?1,'account_disabled',?2,?3)",
                params![crypto::random_token(),account,now])?;
            Ok(())
        })
    }
}

pub fn private_directory(path: &std::path::Path) -> Result<()> {
    if path.exists() {
        return Ok(());
    }
    let mut builder = std::fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(path)?;
    Ok(())
}

pub fn private_file(path: &std::path::Path, bytes: &[u8]) -> Result<()> {
    use std::io::Write;
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

#[derive(Clone)]
pub struct RequestRecord {
    pub id: String,
    pub actor_id: String,
    pub client_id: String,
    pub target_service: String,
    pub purpose: String,
    pub permissions: Vec<Permission>,
    pub expected_human_id: Option<String>,
    pub human_link: String,
    pub phase: String,
    pub created_at: i64,
    pub status_updated_at: i64,
    pub expires_at: i64,
    pub requested_grant_expires_at: i64,
    pub next_poll_at: i64,
    pub poll_interval: i64,
}

pub fn request_record(db: &Connection, id: &str) -> Result<RequestRecord> {
    let data=db.query_row("SELECT id,actor_id,client_id,target_service,purpose,permissions,expected_human_id,
        human_link,phase,created_at,status_updated_at,expires_at,requested_grant_expires_at,next_poll_at,poll_interval
        FROM requests WHERE id=?1",params![id],|r| {
            Ok((RequestRecord {
                id:r.get(0)?,actor_id:r.get(1)?,client_id:r.get(2)?,target_service:r.get(3)?,
                purpose:r.get(4)?,permissions:vec![],expected_human_id:r.get(6)?,human_link:r.get(7)?,
                phase:r.get(8)?,created_at:r.get(9)?,status_updated_at:r.get(10)?,expires_at:r.get(11)?,
                requested_grant_expires_at:r.get(12)?,next_poll_at:r.get(13)?,poll_interval:r.get(14)?,
            },r.get::<_,String>(5)?))
        }).optional()?.ok_or_else(Error::not_found)?;
    let (mut request, permissions) = data;
    request.permissions = serde_json::from_str(&permissions)?;
    Ok(request)
}

pub fn request_by_link(db: &Connection, link: &str) -> Result<RequestRecord> {
    let id = db
        .query_row(
            "SELECT id FROM requests WHERE human_link=?1",
            params![link],
            |r| r.get::<_, String>(0),
        )
        .optional()?
        .ok_or_else(Error::not_found)?;
    request_record(db, &id)
}

pub fn own_request(db: &Connection, id: &str, actor: &str) -> Result<RequestRecord> {
    let request = request_record(db, id)?;
    if request.actor_id != actor {
        return Err(Error::not_found());
    }
    Ok(request)
}

pub fn require_open(request: &RequestRecord, now: i64) -> Result<()> {
    if request.expires_at <= now || request.phase == "expired" {
        return Err(Error::new(
            410,
            "expired",
            "This authorization request has expired.",
        ));
    }
    if ["succeeded", "rejected", "cancelled"].contains(&request.phase.as_str()) {
        return Err(Error::state());
    }
    Ok(())
}

pub fn state_object(
    db: &Connection,
    config: &Config,
    request: &RequestRecord,
    now: i64,
) -> Result<State> {
    let (status, status_text) = display_state(&request.phase)?;
    let human_url = format!("{}/human/{}", config.public_origin, request.human_link);
    let last_mail: Option<i64> = db.query_row(
        "SELECT max(requested_at) FROM mail_operations WHERE request_id=?1",
        params![request.id],
        |r| r.get(0),
    )?;
    let grant=db.query_row("SELECT g.id,g.expires_at,g.revoked_at,EXISTS(SELECT 1 FROM sessions s WHERE s.grant_id=g.id),
        (SELECT enabled FROM accounts WHERE id=g.human_id) FROM grants g WHERE g.request_id=?1",
        params![request.id],|r| Ok((r.get::<_,String>(0)?,r.get::<_,i64>(1)?,r.get::<_,Option<i64>>(2)?,r.get::<_,bool>(3)?,r.get::<_,bool>(4)?))).optional()?;
    let (grant_id, grant_status, grant_expires_at) = match grant {
        None => (None, "none".into(), None),
        Some((id, expires, revoked, issued, enabled)) => {
            let mut statement = db.prepare(
                "SELECT value FROM json_each((SELECT permissions FROM grants WHERE id=?1))",
            )?;
            let permissions = statement.query_map(params![id], |row| row.get::<_, String>(0))?;
            let (mut original, mut effective) = (0, 0);
            let human: String = db.query_row(
                "SELECT human_id FROM grants WHERE id=?1",
                params![id],
                |row| row.get(0),
            )?;
            for permission in permissions {
                original += 1;
                let permission: Permission = serde_json::from_str(&permission?)?;
                if crate::requests::human_permission(db, &human, &permission)? {
                    effective += 1;
                }
            }
            let status = if revoked.is_some() {
                "revoked"
            } else if expires <= now {
                "expired"
            } else if !enabled {
                "account_disabled"
            } else if !issued && request.phase == "expired" {
                "unclaimed_expired"
            } else if effective == 0 {
                "permissions_removed"
            } else if effective < original {
                "restricted"
            } else if issued {
                "active"
            } else {
                "pending_claim"
            };
            (Some(id), status.into(), Some(expires))
        }
    };
    let terminal =
        ["succeeded", "rejected", "cancelled", "expired"].contains(&request.phase.as_str());
    Ok(State {
        protocol_version:PROTOCOL.into(),request_id:request.id.clone(),status,status_text,
        phase:request.phase.clone(),created_at:request.created_at,status_updated_at:request.status_updated_at,
        checked_at:now,expires_at:request.expires_at,poll_after_seconds:if terminal {0} else {request.poll_interval},
        human_authorization_url:human_url.clone(),requested_permissions:request.permissions.clone(),
        email_request_status:if config.mail.mode=="disabled" {"unavailable"} else if last_mail.is_some() {"accepted"} else {"not_requested"}.into(),
        email_retry_after_seconds:last_mail.map(|last|(last+config.mail.recipient_cooldown_seconds-now).max(0)).unwrap_or(0),
        target_service:request.target_service.clone(),client_id:request.client_id.clone(),
        forwarding_prompt:format!("Please open {human_url} on your own device. Verify the requesting key and the exact permissions. Sign in, then approve only the access you choose, or refuse. Do not send your password, cookie, or private key to the AI."),
        grant_id,grant_status,grant_expires_at,
    })
}

pub fn check_rate(db: &Connection, buckets: &[(String, i64)], now: i64) -> Result<()> {
    for (bucket, limit) in buckets {
        let count: i64 = db.query_row(
            "SELECT count(*) FROM rate_events WHERE bucket=?1 AND occurred_at>?2",
            params![bucket, now - 3600],
            |r| r.get(0),
        )?;
        if count >= *limit {
            let mut error = Error::new(
                429,
                "rate_limited",
                "The service cannot accept this operation yet.",
            );
            error.retry_after_seconds = 60;
            return Err(error);
        }
    }
    for (bucket, _) in buckets {
        db.execute(
            "INSERT INTO rate_events(bucket,occurred_at) VALUES(?1,?2)",
            params![bucket, now],
        )?;
    }
    Ok(())
}

pub fn registered_human(db: &Connection, actor: &str) -> Result<String> {
    db.query_row(
        "SELECT id FROM accounts WHERE key_id=?1 AND enabled=1",
        params![actor],
        |r| r.get::<_, String>(0),
    )
    .optional()?
    .ok_or_else(Error::forbidden)
}

pub fn privacy_hash(db: &Connection, text: &str) -> Result<String> {
    let key: String = db.query_row(
        "SELECT value FROM settings WHERE key='privacy_key'",
        [],
        |r| r.get(0),
    )?;
    crypto::private_hash(key.as_bytes(), text)
}
