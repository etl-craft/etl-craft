SELECT TABLE_NAME AS table_name,COLUMN_NAME AS column_name,SUBJECT_KEY AS subject_key,
 KEY_HMAC AS key_hmac,ACTIVE_FLAG AS active_flag,REASON AS reason,CREATED_BY AS created_by,
 CREATED_AT AS created_at,LIFTED_BY AS lifted_by,LIFTED_AT AS lifted_at,LIFT_REASON AS lift_reason
FROM AUD_ERASURE_SUBJECTS WHERE PROJECT_ID=:project_id AND (:all_entries OR ACTIVE_FLAG='Y')
ORDER BY KEY_HMAC,CREATED_AT
