-- One cell per task run on the selected history page.
SELECT t.TASK_CODE AS task_code, r.TASK_RUN_ID AS task_run_id,
       r.PIPELINE_RUN_ID AS pipeline_run_id, r.STATUS AS status,
       r.ATTEMPT_COUNT AS attempt_count, r.START_DATE AS start_date, r.END_DATE AS end_date,
       r.TASK_RUN_LABEL AS task_run_label,
       (SELECT a.ATTEMPT_ID FROM AUD_TASK_ATTEMPTS a WHERE a.TASK_RUN_ID = r.TASK_RUN_ID
        ORDER BY a.ATTEMPT_NUMBER DESC LIMIT 1) AS attempt_id
FROM AUD_TASK_RUN_LOG r
JOIN CFG_TASKS t ON t.TASK_ID = r.TASK_ID
WHERE r.PIPELINE_RUN_ID IN :run_ids
