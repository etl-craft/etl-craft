-- The state of each of :task_ids under :pipeline_run_id: status, counts, attempts, times and
-- the latest attempt's failure class, as run conditions read them.
SELECT l.TASK_ID AS task_id, l.STATUS AS status, l.SOURCE_COUNT AS source_count,
       l.TARGET_COUNT AS target_count, l.ROWS_WRITTEN AS rows_written,
       l.INSERT_COUNT AS insert_count, l.UPDATE_COUNT AS update_count,
       l.DELETE_COUNT AS delete_count, l.REJECT_COUNT AS reject_count,
       l.DUPLICATE_COUNT AS duplicate_count, l.ATTEMPT_COUNT AS attempt_count,
       l.START_DATE AS start_date, l.END_DATE AS end_date,
       (SELECT a.STATUS FROM AUD_TASK_ATTEMPTS a WHERE a.TASK_RUN_ID = l.TASK_RUN_ID
        ORDER BY a.ATTEMPT_ID DESC LIMIT 1) AS attempt_status,
       (SELECT a.FAILURE_CLASS FROM AUD_TASK_ATTEMPTS a WHERE a.TASK_RUN_ID = l.TASK_RUN_ID
        ORDER BY a.ATTEMPT_ID DESC LIMIT 1) AS error_class
FROM AUD_TASK_RUN_LOG l
WHERE l.PIPELINE_RUN_ID = :pipeline_run_id AND l.TASK_ID IN :task_ids
