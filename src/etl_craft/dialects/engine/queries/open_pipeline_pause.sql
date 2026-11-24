-- The open pause of :pipeline_id, if it is paused.
SELECT pause.PAUSED_AT AS paused_at, pause.PAUSED_BY AS paused_by,
       pause.REASON AS reason, pause.ACTIVE_RUNS AS active_runs, p.PROJECT_ID AS project_id
FROM AUD_PIPELINE_PAUSES pause JOIN CFG_PIPELINES p ON p.PIPELINE_ID=pause.PIPELINE_ID
WHERE pause.PIPELINE_ID = :pipeline_id AND pause.RESUMED_AT IS NULL AND pause.TASK_ID IS NULL
