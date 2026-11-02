WITH fencing AS ({{protection_read_fence}}), previous AS ({{protection_request}}),
 first_pending AS ({{protection_first_pending}})
INSERT INTO AUD_PROTECTION_EVENTS
(PROJECT_ID,TARGET_ID,REQUEST_ID,ATTEMPT_ID,KIND,KEY_HASH,COLUMN_NAMES,VALUE_HASHES,STATUS,
 CREATED_BY,CREATED_AT,RECOVERING_ATTEMPT_ID,RECOVERY_ACTOR)
SELECT :project_id,:target,:request_id,:attempt_id,j.value->>'kind',j.value->>'key_hash',
 j.value->>'columns',j.value->>'hashes','PENDING',:actor,:now,NULL,NULL
FROM jsonb_array_elements(CAST(:events AS jsonb)) j(value) CROSS JOIN fencing f WHERE f.live_attempt AND f.lock_owned
 AND (NOT :continuation OR EXISTS (SELECT 1 AS owned FROM previous p
 WHERE (p.attempt_id=:attempt_id OR (p.attempt_id IS NULL AND CAST(:attempt_id AS bigint) IS NULL))
 AND p.final_status IS NULL))
RETURNING EVENT_ID AS event_id
