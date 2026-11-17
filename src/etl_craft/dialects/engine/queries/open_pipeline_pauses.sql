-- Every paused pipeline, by code, with its open pause.
SELECT p.PIPELINE_ID AS pipeline_id,p.PIPELINE_CODE AS pipeline_code, a.PAUSED_AT AS paused_at, a.PAUSED_BY AS paused_by,
       a.REASON AS reason, a.ACTIVE_RUNS AS active_runs
FROM AUD_PIPELINE_PAUSES a
JOIN CFG_PIPELINES p ON p.PIPELINE_ID = a.PIPELINE_ID
WHERE a.RESUMED_AT IS NULL AND a.TASK_ID IS NULL AND p.PROJECT_ID=:project_id
ORDER BY p.PIPELINE_CODE
