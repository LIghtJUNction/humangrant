SELECT
 NOT EXISTS(SELECT 1 FROM mail_blocks WHERE recipient_hash=:recipient_hash)
 AND NOT EXISTS(SELECT 1 FROM mail_operations WHERE recipient_hash=:recipient_hash
   AND state!='suppressed' AND requested_at>hg_now()-:cooldown)
 AND (SELECT count(*) FROM mail_operations WHERE recipient_hash=:recipient_hash
   AND state!='suppressed' AND requested_at>hg_now()-3600)<:recipient_hour
 AND (SELECT count(*) FROM mail_operations WHERE recipient_hash=:recipient_hash
   AND state!='suppressed' AND requested_at>hg_now()-86400)<:recipient_day
 AND (SELECT count(*) FROM mail_operations WHERE actor_id=:actor
   AND state!='suppressed' AND requested_at>hg_now()-3600)<:actor_hour
 AND (SELECT count(*) FROM mail_operations WHERE source_hash=:source
   AND state!='suppressed' AND requested_at>hg_now()-3600)<:source_hour
 AND (SELECT count(*) FROM mail_operations WHERE state!='suppressed'
   AND requested_at>hg_now()-3600)<:service_hour
 AND (SELECT count(*) FROM mail_operations WHERE state!='suppressed'
   AND requested_at>hg_now()-86400)<:service_day;
