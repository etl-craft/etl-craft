INSERT INTO AUD_PIPELINE_REPARSES
(PROJECT_ID,PIPELINE_ID,REPARSED_AT,ACTOR,ACTOR_KIND,STATUS,METADATA_VERSION,METADATA_SNAPSHOT,SNAPSHOT_REPARSE_ID,BUNDLE_ID,FINDINGS)
VALUES (:project_id,:pipeline_id,:now,:actor,:actor_kind,:status,:metadata_version,:snapshot,:snapshot_reparse_id,:bundle_id,:findings)
RETURNING REPARSE_ID AS reparse_id
