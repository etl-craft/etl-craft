INSERT INTO AUD_ERASURE_SUBJECTS
(PROJECT_ID,TABLE_NAME,COLUMN_NAME,SUBJECT_KEY,KEY_HMAC,REASON,CREATED_BY,CREATED_AT,KEY_CHECK)
VALUES (:project_id,:table_name,:column_name,:subject_key,:key_hmac,:reason,:actor,:now,:key_check)
