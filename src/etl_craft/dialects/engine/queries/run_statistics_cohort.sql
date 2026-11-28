WITH ranked AS (
    SELECT r.TASK_ID AS task_id, r.TASK_RUN_ID AS task_run_id,
           ROW_NUMBER() OVER (
               PARTITION BY r.TASK_ID ORDER BY r.END_DATE DESC NULLS LAST, r.TASK_RUN_ID DESC
           ) AS sample
    FROM AUD_TASK_RUN_LOG r
    JOIN CFG_TASKS t ON t.TASK_ID = r.TASK_ID
    JOIN AUD_PIPELINES_RUN_LOG p ON p.PIPELINE_ID = t.PIPELINE_ID
    WHERE p.PIPELINE_RUN_ID = :run_id AND r.STATUS = :status
)
SELECT ranked.task_id AS task_id, a.STARTED_AT AS started_at, a.ENDED_AT AS ended_at
FROM ranked
JOIN AUD_TASK_ATTEMPTS a ON a.TASK_RUN_ID = ranked.task_run_id
WHERE ranked.sample <= 20 AND a.ATTEMPT_NUMBER = (
    SELECT MAX(last_try.ATTEMPT_NUMBER) FROM AUD_TASK_ATTEMPTS last_try
    WHERE last_try.TASK_RUN_ID = ranked.task_run_id
)
