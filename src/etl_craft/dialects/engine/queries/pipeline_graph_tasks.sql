-- Every active task in :pipeline_id, with its run condition and its pipeline's and project's codes.
SELECT t.TASK_ID AS task_id, t.TASK_CODE AS task_code, t.RUN_CONDITION AS run_condition,
       t.HANDLER AS handler, p.PIPELINE_CODE AS pipeline_code, project.PROJECT_CODE AS project_code
FROM CFG_TASKS t
JOIN CFG_PIPELINES p ON p.PIPELINE_ID = t.PIPELINE_ID
JOIN CFG_PROJECTS project ON project.PROJECT_ID = p.PROJECT_ID
WHERE t.PIPELINE_ID = :pipeline_id AND t.ACTIVE_FLAG = 'Y'
ORDER BY t.TASK_ID
