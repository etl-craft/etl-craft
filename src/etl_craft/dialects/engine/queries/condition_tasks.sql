-- Every task of the selected project with its pipeline and run condition, for deriving edges.
SELECT t.TASK_ID AS task_id, pr.PROJECT_CODE AS project_code, t.TASK_CODE AS task_code, t.PIPELINE_ID AS pipeline_id,
       p.PIPELINE_CODE AS pipeline_code, t.RUN_CONDITION AS run_condition,
       CASE WHEN t.ACTIVE_FLAG = 'Y' AND p.ACTIVE_FLAG = 'Y' THEN 1 ELSE 0 END AS active
FROM CFG_TASKS t JOIN CFG_PIPELINES p ON p.PIPELINE_ID = t.PIPELINE_ID
JOIN CFG_PROJECTS pr ON pr.PROJECT_ID = p.PROJECT_ID
WHERE p.PROJECT_ID = :project_id
ORDER BY p.PIPELINE_CODE, t.TASK_CODE
