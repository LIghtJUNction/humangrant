BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, key_id TEXT NOT NULL UNIQUE, public_key TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, target_service TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS service_policy (
  target_service TEXT NOT NULL, action TEXT NOT NULL,
  PRIMARY KEY(target_service,action)
);
CREATE TABLE IF NOT EXISTS resources (
  target_service TEXT NOT NULL, id TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES accounts(id),
  content TEXT NOT NULL, PRIMARY KEY(target_service,id)
);
CREATE TABLE IF NOT EXISTS entitlements (
  account_id TEXT NOT NULL REFERENCES accounts(id), target_service TEXT NOT NULL,
  action TEXT NOT NULL, resource TEXT NOT NULL,
  PRIMARY KEY(account_id,target_service,action,resource),
  FOREIGN KEY(target_service,action) REFERENCES service_policy(target_service,action),
  FOREIGN KEY(target_service,resource) REFERENCES resources(target_service,id)
);
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, actor_public_key TEXT NOT NULL,
  client_id TEXT NOT NULL REFERENCES clients(id), target_service TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK(length(purpose)<=240),
  permissions TEXT NOT NULL CHECK(json_valid(permissions) AND json_type(permissions)='array'
    AND json_array_length(permissions) BETWEEN 1 AND 16),
  expected_human_id TEXT,
  human_link TEXT NOT NULL UNIQUE,
  phase TEXT NOT NULL CHECK(phase IN ('waiting_human','authenticating_human','awaiting_consent',
    'approved','succeeded','rejected','expired','cancelled')),
  created_at INTEGER NOT NULL, status_updated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  requested_grant_expires_at INTEGER NOT NULL,
  next_poll_at INTEGER NOT NULL DEFAULT 0, poll_interval INTEGER NOT NULL DEFAULT 5,
  audit_id TEXT NOT NULL UNIQUE,
  CHECK(expires_at>created_at AND requested_grant_expires_at>created_at),
  CHECK(poll_interval BETWEEN 1 AND 60)
);
CREATE INDEX IF NOT EXISTS requests_actor ON requests(actor_id,created_at);
CREATE TABLE IF NOT EXISTS grants (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES requests(id),
  human_id TEXT NOT NULL REFERENCES accounts(id), actor_id TEXT NOT NULL,
  public_key_id TEXT NOT NULL, client_id TEXT NOT NULL, target_service TEXT NOT NULL,
  permissions TEXT NOT NULL CHECK(json_valid(permissions) AND json_type(permissions)='array'
    AND json_array_length(permissions) BETWEEN 1 AND 16),
  created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER,
  audit_id TEXT NOT NULL,
  CHECK(expires_at>created_at)
);
CREATE INDEX IF NOT EXISTS grants_human ON grants(human_id,created_at);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES requests(id),
  grant_id TEXT NOT NULL UNIQUE REFERENCES grants(id), actor_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS browser_sessions (
  token_hash TEXT PRIMARY KEY, request_id TEXT REFERENCES requests(id), csrf TEXT NOT NULL,
  human_id TEXT REFERENCES accounts(id), expires_at INTEGER NOT NULL,
  challenge TEXT, challenge_expires_at INTEGER, challenge_used INTEGER NOT NULL DEFAULT 0,
  CHECK(challenge_used IN (0,1))
);
CREATE TABLE IF NOT EXISTS nonces (
  key_id TEXT NOT NULL, nonce TEXT NOT NULL, expires_at INTEGER NOT NULL,
  PRIMARY KEY(key_id,nonce)
);
CREATE INDEX IF NOT EXISTS nonces_expiry ON nonces(expires_at);
CREATE TABLE IF NOT EXISTS rate_events (
  id INTEGER PRIMARY KEY, bucket TEXT NOT NULL, occurred_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_bucket_time ON rate_events(bucket,occurred_at);
CREATE TABLE IF NOT EXISTS mail_operations (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(id), actor_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL, recipient_hash TEXT NOT NULL, source_hash TEXT NOT NULL,
  recipient TEXT, requested_at INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('queued','suppressed','sending','local_spooled',
    'transport_accepted','failed','delivery_unknown','expired')),
  action_token TEXT NOT NULL UNIQUE, subject TEXT NOT NULL, body TEXT NOT NULL,
  transport_updated_at INTEGER NOT NULL,
  UNIQUE(actor_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS mail_recipient_time ON mail_operations(recipient_hash,requested_at);
CREATE INDEX IF NOT EXISTS mail_actor_time ON mail_operations(actor_id,requested_at);
CREATE INDEX IF NOT EXISTS mail_source_time ON mail_operations(source_hash,requested_at);
CREATE INDEX IF NOT EXISTS mail_queue ON mail_operations(state,requested_at);
CREATE TABLE IF NOT EXISTS mail_blocks (
  recipient_hash TEXT PRIMARY KEY, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  sequence INTEGER PRIMARY KEY, audit_id TEXT NOT NULL, event TEXT NOT NULL,
  request_id TEXT, actor_id TEXT, human_id TEXT, occurred_at INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS request_insert_guard BEFORE INSERT ON requests BEGIN
  SELECT CASE WHEN NEW.phase!='waiting_human' OR NEW.created_at!=hg_now()
    OR NEW.status_updated_at!=hg_now() OR NEW.expires_at<=hg_now()
    OR NOT EXISTS(SELECT 1 FROM clients WHERE id=NEW.client_id AND target_service=NEW.target_service)
    THEN RAISE(ABORT,'request_invalid') END;
  SELECT CASE WHEN EXISTS(
    SELECT 1 FROM json_each(NEW.permissions) p WHERE json_type(p.value)!='object'
      OR json_type(p.value,'$.action') IS NOT 'text' OR json_type(p.value,'$.resource') IS NOT 'text'
      OR NOT EXISTS(SELECT 1 FROM service_policy s WHERE s.target_service=NEW.target_service
        AND s.action=json_extract(p.value,'$.action'))
  ) THEN RAISE(ABORT,'permission_invalid') END;
END;
CREATE TRIGGER IF NOT EXISTS request_immutable BEFORE UPDATE ON requests BEGIN
  SELECT CASE WHEN NEW.id IS NOT OLD.id OR NEW.actor_id IS NOT OLD.actor_id
    OR NEW.actor_public_key IS NOT OLD.actor_public_key OR NEW.client_id IS NOT OLD.client_id
    OR NEW.target_service IS NOT OLD.target_service OR NEW.purpose IS NOT OLD.purpose
    OR NEW.permissions IS NOT OLD.permissions OR NEW.expected_human_id IS NOT OLD.expected_human_id
    OR NEW.human_link IS NOT OLD.human_link OR NEW.created_at IS NOT OLD.created_at
    OR NEW.expires_at IS NOT OLD.expires_at
    OR NEW.requested_grant_expires_at IS NOT OLD.requested_grant_expires_at
    OR NEW.audit_id IS NOT OLD.audit_id THEN RAISE(ABORT,'request_immutable') END;
  SELECT CASE WHEN (NEW.phase=OLD.phase AND NEW.status_updated_at!=OLD.status_updated_at)
    OR (NEW.phase!=OLD.phase AND NEW.status_updated_at!=hg_now())
    THEN RAISE(ABORT,'state_timestamp_invalid') END;
  SELECT CASE WHEN NEW.phase!=OLD.phase AND NOT (
    (OLD.phase='waiting_human' AND NEW.phase IN ('authenticating_human','rejected','cancelled','expired')) OR
    (OLD.phase='authenticating_human' AND NEW.phase IN ('awaiting_consent','rejected','cancelled','expired')) OR
    (OLD.phase='awaiting_consent' AND NEW.phase IN ('approved','rejected','cancelled','expired')) OR
    (OLD.phase='approved' AND NEW.phase IN ('succeeded','cancelled','expired'))
  ) THEN RAISE(ABORT,'invalid_transition') END;
  SELECT CASE WHEN NEW.phase!=OLD.phase AND NEW.phase NOT IN ('expired','cancelled')
    AND OLD.expires_at<=hg_now() THEN RAISE(ABORT,'request_expired') END;
END;
CREATE TRIGGER IF NOT EXISTS request_created AFTER INSERT ON requests BEGIN
  INSERT INTO audit(audit_id,event,request_id,actor_id,occurred_at)
    VALUES(NEW.audit_id,'request_created',NEW.id,NEW.actor_id,hg_now());
END;
CREATE TRIGGER IF NOT EXISTS request_changed AFTER UPDATE OF phase ON requests
WHEN NEW.phase!=OLD.phase BEGIN
  INSERT INTO audit(audit_id,event,request_id,actor_id,occurred_at)
    VALUES(NEW.audit_id,NEW.phase,NEW.id,NEW.actor_id,hg_now());
END;

CREATE TRIGGER IF NOT EXISTS grant_insert_guard BEFORE INSERT ON grants BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM requests r JOIN accounts a ON a.id=NEW.human_id
    WHERE r.id=NEW.request_id AND r.phase='awaiting_consent' AND r.expires_at>hg_now()
      AND a.enabled=1 AND (r.expected_human_id IS NULL OR r.expected_human_id=NEW.human_id)
      AND NEW.actor_id=r.actor_id AND NEW.public_key_id=r.actor_id AND NEW.client_id=r.client_id
      AND NEW.target_service=r.target_service AND NEW.audit_id=r.audit_id
      AND NEW.created_at=hg_now() AND NEW.expires_at<=r.requested_grant_expires_at
      AND NEW.expires_at>hg_now() AND NEW.revoked_at IS NULL)
    THEN RAISE(ABORT,'grant_binding_invalid') END;
  SELECT CASE WHEN EXISTS(SELECT 1 FROM json_each(NEW.permissions) p WHERE
    json_type(p.value)!='object' OR json_type(p.value,'$.action') IS NOT 'text'
    OR json_type(p.value,'$.resource') IS NOT 'text'
    OR NOT EXISTS(SELECT 1 FROM requests r,json_each(r.permissions) q
       WHERE r.id=NEW.request_id AND json_extract(q.value,'$.action')=json_extract(p.value,'$.action')
       AND json_extract(q.value,'$.resource')=json_extract(p.value,'$.resource'))
    OR NOT EXISTS(SELECT 1 FROM entitlements e JOIN accounts a ON a.id=e.account_id
       JOIN resources z ON z.target_service=e.target_service AND z.id=e.resource
       JOIN service_policy s ON s.target_service=e.target_service AND s.action=e.action
       WHERE e.account_id=NEW.human_id AND a.enabled=1 AND z.owner_id=NEW.human_id
       AND e.target_service=NEW.target_service AND e.action=json_extract(p.value,'$.action')
       AND e.resource=json_extract(p.value,'$.resource'))
  ) THEN RAISE(ABORT,'grant_permission_invalid') END;
  SELECT CASE WHEN EXISTS(SELECT 1 FROM json_each(NEW.permissions)
    GROUP BY json_extract(value,'$.action'),json_extract(value,'$.resource') HAVING count(*)>1)
    THEN RAISE(ABORT,'grant_permission_duplicate') END;
END;
CREATE TRIGGER IF NOT EXISTS grant_created AFTER INSERT ON grants BEGIN
  UPDATE requests SET phase='approved',status_updated_at=hg_now() WHERE id=NEW.request_id;
  INSERT INTO audit(audit_id,event,request_id,actor_id,human_id,occurred_at)
    VALUES(NEW.audit_id,'grant_approved',NEW.request_id,NEW.actor_id,NEW.human_id,hg_now());
END;
CREATE TRIGGER IF NOT EXISTS grant_immutable BEFORE UPDATE ON grants BEGIN
  SELECT CASE WHEN NEW.id IS NOT OLD.id OR NEW.request_id IS NOT OLD.request_id
    OR NEW.human_id IS NOT OLD.human_id OR NEW.actor_id IS NOT OLD.actor_id
    OR NEW.public_key_id IS NOT OLD.public_key_id OR NEW.client_id IS NOT OLD.client_id
    OR NEW.target_service IS NOT OLD.target_service OR NEW.permissions IS NOT OLD.permissions
    OR NEW.created_at IS NOT OLD.created_at OR NEW.expires_at IS NOT OLD.expires_at
    OR NEW.audit_id IS NOT OLD.audit_id
    OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS NOT OLD.revoked_at)
    OR (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL AND NEW.revoked_at!=hg_now())
    THEN RAISE(ABORT,'grant_immutable') END;
END;
CREATE TRIGGER IF NOT EXISTS grant_revoked AFTER UPDATE OF revoked_at ON grants
WHEN OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL BEGIN
  UPDATE requests SET phase='cancelled',status_updated_at=hg_now()
    WHERE id=NEW.request_id AND phase='approved';
  INSERT INTO audit(audit_id,event,request_id,actor_id,human_id,occurred_at)
    VALUES(NEW.audit_id,'grant_revoked',NEW.request_id,NEW.actor_id,NEW.human_id,hg_now());
END;
CREATE TRIGGER IF NOT EXISTS session_insert_guard BEFORE INSERT ON sessions BEGIN
  SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM grants g JOIN requests r ON r.id=g.request_id
    JOIN accounts a ON a.id=g.human_id WHERE g.id=NEW.grant_id AND g.request_id=NEW.request_id
    AND r.phase='approved' AND r.expires_at>hg_now() AND g.revoked_at IS NULL
    AND g.expires_at>hg_now() AND a.enabled=1 AND NEW.actor_id=g.actor_id
    AND NEW.created_at=hg_now()) THEN RAISE(ABORT,'session_binding_invalid') END;
END;
CREATE TRIGGER IF NOT EXISTS session_created AFTER INSERT ON sessions BEGIN
  UPDATE requests SET phase='succeeded',status_updated_at=hg_now() WHERE id=NEW.request_id;
END;
CREATE TRIGGER IF NOT EXISTS session_immutable BEFORE UPDATE ON sessions BEGIN
  SELECT RAISE(ABORT,'session_immutable');
END;
CREATE TRIGGER IF NOT EXISTS session_no_delete BEFORE DELETE ON sessions BEGIN
  SELECT RAISE(ABORT,'revoke_grant_instead');
END;
PRAGMA user_version=1;
COMMIT;
