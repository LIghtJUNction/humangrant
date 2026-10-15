BEGIN IMMEDIATE;
DROP TRIGGER request_immutable;
CREATE TRIGGER request_immutable BEFORE UPDATE ON requests BEGIN
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
    (OLD.phase='waiting_human' AND NEW.phase IN ('authenticating_human','awaiting_consent','rejected','cancelled','expired')) OR
    (OLD.phase='authenticating_human' AND NEW.phase IN ('awaiting_consent','rejected','cancelled','expired')) OR
    (OLD.phase='awaiting_consent' AND NEW.phase IN ('approved','rejected','cancelled','expired')) OR
    (OLD.phase='approved' AND NEW.phase IN ('succeeded','cancelled','expired'))
  ) THEN RAISE(ABORT,'invalid_transition') END;
  SELECT CASE WHEN NEW.phase!=OLD.phase AND NEW.phase NOT IN ('expired','cancelled')
    AND OLD.expires_at<=hg_now() THEN RAISE(ABORT,'request_expired') END;
END;
PRAGMA user_version=2;
COMMIT;
