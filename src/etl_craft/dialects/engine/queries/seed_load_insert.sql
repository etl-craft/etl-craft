INSERT INTO AUD_SEED_LOADS
(PROJECT_ID,CATALOG_NAME,SCHEMA_NAME,TABLE_NAME,CONTENT_SHA256,SEED_LOAD_ID,STATUS,
 ERROR_MESSAGE,CREATED_BY,CREATED_AT)
VALUES (:project_id,:catalog_name,:schema_name,:table_name,:content_sha256,:seed_load_id,
 :status,:error_message,:actor,:now)
