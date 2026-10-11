INSERT INTO sessions(id,request_id,grant_id,actor_id,token_hash,created_at)
SELECT :id,r.id,g.id,:actor,:token_hash,hg_now()
FROM requests r JOIN grants g ON g.request_id=r.id
WHERE r.id=:request AND r.actor_id=:actor;
