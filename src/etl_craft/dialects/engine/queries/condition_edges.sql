-- The derived task edges of the selected project, active or not.
SELECT d.TASK_DEPENDENCY_ID AS task_dependency_id, d.TASK_ID AS task_id,
       d.DEPENDS_ON_TASK_ID AS depends_on_task_id, d.ACTIVE_FLAG AS active_flag
FROM CFG_TASK_DEPENDENCY d JOIN CFG_PIPELINES p ON p.PIPELINE_ID = d.PIPELINE_ID
WHERE p.PROJECT_ID = :project_id
