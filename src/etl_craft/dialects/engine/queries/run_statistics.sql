SELECT p.PIPELINE_ID AS pipeline_id, r.TASK_ID AS task_id, r.STATUS AS task_status,
       r.ERROR_MESSAGE AS task_error_message, a.ATTEMPT_ID AS attempt_id,
       a.STATUS AS status, a.ATTEMPT_NUMBER AS attempt_number,
       a.STARTED_AT AS started_at, a.ENDED_AT AS ended_at,
       a.SOURCE_COUNT AS source_count, a.ROWS_WRITTEN AS rows_written,
       a.REJECT_COUNT AS reject_count, a.PEAK_RSS_BYTES AS peak_rss_bytes,
       a.CPU_SECONDS AS cpu_seconds, a.ERROR_MESSAGE AS error_message,
       a.FAILURE_CODE AS failure_code,
       COALESCE(a.LAST_ERROR_EXIT_CODE, a.FIRST_ERROR_EXIT_CODE) AS exit_name
FROM AUD_PIPELINES_RUN_LOG p
LEFT JOIN AUD_TASK_RUN_LOG r ON r.PIPELINE_RUN_ID = p.PIPELINE_RUN_ID
LEFT JOIN AUD_TASK_ATTEMPTS a ON a.TASK_RUN_ID = r.TASK_RUN_ID
WHERE p.PIPELINE_RUN_ID = :run_id
ORDER BY r.TASK_ID, a.ATTEMPT_NUMBER
