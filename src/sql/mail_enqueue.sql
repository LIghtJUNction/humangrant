INSERT INTO mail_operations(id,request_id,actor_id,idempotency_key,recipient_hash,source_hash,
 recipient,requested_at,state,action_token,subject,body,transport_updated_at)
VALUES(:id,:request,:actor,:key,:recipient_hash,:source,:recipient,hg_now(),:state,:action_token,
 :subject,:body,hg_now());
