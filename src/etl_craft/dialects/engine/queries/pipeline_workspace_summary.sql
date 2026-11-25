-- Run and admission facts for the selected pipeline's workspace.
SELECT p.STEWARDABLE_FLAG AS stewardable,
       EXISTS (
           SELECT 1 FROM CFG_TASKS t
           WHERE t.PIPELINE_ID = p.PIPELINE_ID AND t.ACTIVE_FLAG = 'Y' AND t.HANDLER = 'EVENT_WAIT'
       ) AS waits_for_events,
       r.PIPELINE_RUN_ID AS pipeline_run_id, r.STATUS AS status, r.SLA_STATUS AS sla_status,
       r.START_DATE AS start_date, r.END_DATE AS end_date
FROM CFG_PIPELINES p
LEFT JOIN AUD_PIPELINES_RUN_LOG r ON r.PIPELINE_RUN_ID = (
    SELECT whole.PIPELINE_RUN_ID FROM AUD_PIPELINES_RUN_LOG whole
    WHERE whole.PIPELINE_ID = p.PIPELINE_ID AND whole.TASK_SELECTION IS NULL
    ORDER BY whole.PIPELINE_RUN_ID DESC LIMIT 1
)
WHERE p.PIPELINE_ID = :pipeline_id AND p.PROJECT_ID = :project_id
