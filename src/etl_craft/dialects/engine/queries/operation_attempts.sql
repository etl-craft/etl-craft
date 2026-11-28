-- Attempts retain their order and the identities of their task and pipeline runs.
SELECT p.PIPELINE_ID AS pipeline_id, r.PIPELINE_RUN_ID AS pipeline_run_id,
       r.TASK_ID AS task_id, a.TASK_RUN_ID AS task_run_id, a.ATTEMPT_ID AS attempt_id,
       a.ATTEMPT_NUMBER AS attempt_number, a.STATUS AS status, a.OWNER_ID AS owner_id,
       a.LEASE_EXPIRES_AT AS lease_expires_at, a.HEARTBEAT_AT AS heartbeat_at,
       a.QUEUED_AT AS queued_at, a.CLAIMED_AT AS claimed_at, a.STARTED_AT AS started_at,
       a.ENDED_AT AS ended_at, a.HOST AS host, a.PID AS pid, a.PROCESS_START AS process_start,
       (SELECT e.EVIDENCE_KIND FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
        WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'PROCESS') AS process_evidence_kind,
       (SELECT e.ACTOR FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
        WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'PROCESS') AS process_evidence_actor,
       (SELECT e.REASON FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
        WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'PROCESS') AS process_evidence_reason,
       (SELECT e.VERIFIED_CHECKS FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
        WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'PROCESS') AS process_evidence_checks,
       (SELECT e.EVIDENCE_KIND FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
        WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'QUERIES') AS query_evidence_kind,
       (SELECT e.ACTOR FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
        WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'QUERIES') AS query_evidence_actor,
       (SELECT e.REASON FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
        WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'QUERIES') AS query_evidence_reason,
       (SELECT e.VERIFIED_CHECKS FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
        WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'QUERIES') AS query_evidence_checks,
       a.EXIT_CODE AS exit_code, a.SOURCE_COUNT AS source_count, a.TARGET_COUNT AS target_count,
       a.INSERT_COUNT AS insert_count, a.UPDATE_COUNT AS update_count,
       a.DELETE_COUNT AS delete_count, a.ROWS_WRITTEN AS rows_written,
       a.REJECT_COUNT AS reject_count, a.DUPLICATE_COUNT AS duplicate_count,
       a.WATERMARK_FROM AS watermark_from, a.WATERMARK_TO AS watermark_to,        a.ERROR_MESSAGE AS error_message, a.LOG_PATH AS log_path,
       a.REQUESTED_BY AS requested_by, a.REQUESTED_BY_KIND AS requested_by_kind,
       a.NOT_BEFORE AS not_before, a.RETRYABLE AS retryable,
       a.FAILURE_CLASS AS failure_class, a.FAILURE_SOURCE AS failure_source,
       a.FAILURE_CODE AS failure_code, a.RETRY_ON AS retry_on,
       a.FIRST_ERROR_SEQUENCE AS first_sequence,
       a.FIRST_ERROR_STEP AS first_step,
       a.FIRST_ERROR_ERROR_CLASS AS first_error_class,
       a.FIRST_ERROR_EXIT_CODE AS first_exit_name,
       a.FIRST_ERROR_FAILURE_CLASS AS first_class,
       a.FIRST_ERROR_OFFSET AS first_offset,
       a.FIRST_ERROR_LINE AS first_line,
       a.LAST_ERROR_SEQUENCE AS last_sequence,
       a.LAST_ERROR_STEP AS last_step,
       a.LAST_ERROR_ERROR_CLASS AS last_error_class,
       a.LAST_ERROR_EXIT_CODE AS last_exit_name,
       a.LAST_ERROR_FAILURE_CLASS AS last_class,
       a.LAST_ERROR_OFFSET AS last_offset,
       a.LAST_ERROR_LINE AS last_line,
       a.LOG_REMOVED_AT AS log_removed_at, cfg.PROJECT_ID AS log_project_id,
       cfg.PIPELINE_CODE AS log_pipeline_code, task.TASK_CODE AS log_task_code,
       (SELECT ENGINE_ID FROM AUD_ENGINE_IDENTITY WHERE IDENTITY_ID = 1) AS log_engine_id,
       CASE WHEN a.LOG_PATH IS NULL AND a.FIRST_ERROR_SEQUENCE IS NOT NULL THEN
           (WITH RECURSIVE preview(sequence, content, end_offset) AS (
                SELECT c.SEQUENCE_NUMBER, c.CONTENT, c.BYTE_OFFSET + c.BYTE_LENGTH
                FROM AUD_ATTEMPT_LOG_CHUNKS c
                WHERE c.ATTEMPT_ID = a.ATTEMPT_ID AND c.SEQUENCE_NUMBER = 0
                UNION ALL
                SELECT c.SEQUENCE_NUMBER, previous.content || c.CONTENT,
                       c.BYTE_OFFSET + c.BYTE_LENGTH
                FROM preview previous
                JOIN AUD_ATTEMPT_LOG_CHUNKS c
                  ON c.ATTEMPT_ID = a.ATTEMPT_ID AND c.SEQUENCE_NUMBER = previous.sequence + 1
                WHERE previous.sequence < 15 AND previous.end_offset < 65536
            )
            SELECT content FROM preview ORDER BY sequence DESC LIMIT 1)
       END AS log_initial_chunk,
       a.PEAK_RSS_BYTES AS peak_rss_bytes, a.CPU_SECONDS AS cpu_seconds
FROM AUD_TASK_ATTEMPTS a
JOIN AUD_TASK_RUN_LOG r ON r.TASK_RUN_ID = a.TASK_RUN_ID
JOIN AUD_PIPELINES_RUN_LOG p ON p.PIPELINE_RUN_ID = r.PIPELINE_RUN_ID
JOIN CFG_PIPELINES cfg ON cfg.PIPELINE_ID = p.PIPELINE_ID
JOIN CFG_TASKS task ON task.TASK_ID = r.TASK_ID
WHERE a.TASK_RUN_ID = :task_run_id
ORDER BY a.ATTEMPT_NUMBER
