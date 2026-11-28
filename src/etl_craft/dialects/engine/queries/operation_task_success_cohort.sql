SELECT r.START_DATE AS start_date, r.END_DATE AS end_date,
       r.SOURCE_COUNT AS source_count, r.TARGET_COUNT AS target_count,
       r.INSERT_COUNT AS insert_count, r.UPDATE_COUNT AS update_count,
       r.DELETE_COUNT AS delete_count, r.ROWS_WRITTEN AS rows_written,
       r.REJECT_COUNT AS reject_count, r.DUPLICATE_COUNT AS duplicate_count,
       a.ATTEMPT_ID AS attempt_id, a.QUEUED_AT AS queued_at,
       a.STARTED_AT AS started_at, a.ENDED_AT AS ended_at,
       a.PEAK_RSS_BYTES AS peak_rss_bytes, a.CPU_SECONDS AS cpu_seconds
FROM AUD_TASK_RUN_LOG r
LEFT JOIN AUD_TASK_ATTEMPTS a ON a.TASK_RUN_ID = r.TASK_RUN_ID
   AND a.ATTEMPT_NUMBER = (
       SELECT MAX(last_try.ATTEMPT_NUMBER) FROM AUD_TASK_ATTEMPTS last_try
       WHERE last_try.TASK_RUN_ID = r.TASK_RUN_ID
   )
WHERE r.TASK_ID = :task_id AND r.STATUS = :status
ORDER BY r.END_DATE DESC NULLS LAST, r.TASK_RUN_ID DESC
LIMIT 20
