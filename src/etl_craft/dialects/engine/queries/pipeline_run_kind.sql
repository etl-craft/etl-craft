-- The date :pipeline_run_id runs as of, and whether it is a backfill or a full refresh.
SELECT RUN_DATE AS run_date, BACKFILL AS backfill, FULL_REFRESH AS full_refresh
FROM AUD_PIPELINES_RUN_LOG
WHERE PIPELINE_RUN_ID = :pipeline_run_id
