INSERT INTO AUD_PROTECTION_EVENTS
(PROJECT_ID,TARGET_ID,REQUEST_ID,ATTEMPT_ID,KIND,KEY_HASH,COLUMN_NAMES,VALUE_HASHES,STATUS,
 CREATED_BY,CREATED_AT,RECOVERING_ATTEMPT_ID,RECOVERY_ACTOR,UPLOAD_ID)
VALUES (:project_id,:target,:request_id,:attempt_id,:kind,:key_hash,:columns,:hashes,:status,
 :actor,:now,:recovering_attempt,:recovery_actor,:upload_id)
