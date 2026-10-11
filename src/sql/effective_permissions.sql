SELECT DISTINCT json_extract(p.value,'$.action') AS action,
 json_extract(p.value,'$.resource') AS resource
FROM sessions s JOIN grants g ON g.id=s.grant_id JOIN accounts a ON a.id=g.human_id
JOIN clients c ON c.id=g.client_id AND c.target_service=g.target_service,
 json_each(g.permissions) p
JOIN entitlements e ON e.account_id=g.human_id AND e.target_service=g.target_service
 AND e.action=json_extract(p.value,'$.action') AND e.resource=json_extract(p.value,'$.resource')
JOIN resources r ON r.target_service=e.target_service AND r.id=e.resource AND r.owner_id=g.human_id
JOIN service_policy q ON q.target_service=e.target_service AND q.action=e.action
WHERE s.token_hash=:token_hash AND s.actor_id=:actor AND g.actor_id=:actor
 AND g.target_service=:service AND g.revoked_at IS NULL AND g.expires_at>hg_now() AND a.enabled=1
ORDER BY action,resource;
