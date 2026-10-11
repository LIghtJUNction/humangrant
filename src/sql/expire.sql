UPDATE requests SET phase='expired',status_updated_at=hg_now()
 WHERE expires_at<=hg_now() AND phase IN ('waiting_human','authenticating_human','awaiting_consent','approved');
DELETE FROM nonces WHERE expires_at<hg_now();
DELETE FROM browser_sessions WHERE expires_at<=hg_now();
DELETE FROM rate_events WHERE occurred_at<=hg_now()-86400;
UPDATE mail_operations SET state='expired',transport_updated_at=hg_now()
 WHERE state='queued' AND request_id IN (SELECT id FROM requests
   WHERE expires_at<=hg_now() OR phase IN ('rejected','cancelled','expired','succeeded'));
