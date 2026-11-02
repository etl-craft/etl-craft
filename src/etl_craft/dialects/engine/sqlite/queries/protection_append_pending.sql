WITH fencing AS ({{protection_read_fence}}), previous AS ({{protection_request}}),
 first_pending AS ({{protection_first_pending}}), verified_upload AS ({{protection_verified_upload}})
INSERT INTO AUD_PROTECTION_EVENTS
(PROJECT_ID,TARGET_ID,REQUEST_ID,ATTEMPT_ID,KIND,KEY_HASH,COLUMN_NAMES,VALUE_HASHES,STATUS,
 CREATED_BY,CREATED_AT,RECOVERING_ATTEMPT_ID,RECOVERY_ACTOR,UPLOAD_ID)
SELECT :project_id,:target,:request_id,:attempt_id,json_extract(j.value,'$.kind'),json_extract(j.value,'$.key_hash'),
 json_extract(j.value,'$.columns'),json_extract(j.value,'$.hashes'),'PENDING',COALESCE((SELECT uploader FROM verified_upload),:actor),:now,NULL,NULL,(SELECT upload_id FROM verified_upload)
FROM json_each(:events) j CROSS JOIN fencing f WHERE f.live_attempt AND f.lock_owned
 AND (CAST(:upload_id AS bigint) IS NULL OR EXISTS (SELECT 1 AS accepted FROM verified_upload))
 AND (NOT :continuation OR EXISTS (SELECT 1 AS owned FROM previous p
 WHERE (p.attempt_id=:attempt_id OR (p.attempt_id IS NULL AND CAST(:attempt_id AS bigint) IS NULL))
 AND (p.upload_id=:upload_id OR (p.upload_id IS NULL AND CAST(:upload_id AS bigint) IS NULL))
 AND p.final_status IS NULL))
RETURNING EVENT_ID AS event_id
