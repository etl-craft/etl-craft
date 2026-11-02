WITH fencing AS ({{protection_read_fence}}), previous AS ({{protection_request}}),
 first_pending AS ({{protection_first_pending}})
INSERT INTO AUD_PROTECTION_EVENTS
(PROJECT_ID,TARGET_ID,REQUEST_ID,ATTEMPT_ID,KIND,KEY_HASH,COLUMN_NAMES,VALUE_HASHES,STATUS,
 CREATED_BY,CREATED_AT,RECOVERING_ATTEMPT_ID,RECOVERY_ACTOR)
SELECT :project_id,:target,:request_id,p.attempt_id,p.kind,NULL,'[]','[]',:status,
 :actor,:now,NULL,NULL FROM previous p CROSS JOIN fencing f
WHERE f.live_attempt AND f.lock_owned AND p.final_status IS NULL AND p.kind<>'REHASH'
 AND (p.attempt_id=:attempt_id OR (p.attempt_id IS NULL AND CAST(:attempt_id AS bigint) IS NULL))
 AND NOT EXISTS (SELECT 1 AS earlier FROM first_pending q WHERE q.request_id<>:request_id)
RETURNING EVENT_ID AS event_id
