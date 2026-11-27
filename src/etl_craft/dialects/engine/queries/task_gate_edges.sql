-- The active dependencies of :task_id on tasks in other pipelines.
SELECT d.TASK_DEPENDENCY_ID AS task_dependency_id, d.PIPELINE_ID AS pipeline_id,
       d.DEPENDS_ON_PIPELINE_ID AS depends_on_pipeline_id,
       d.DEPENDS_ON_TASK_ID AS depends_on_task_id, (c.CONSUME_REPAIRS = 'Y') AS consume_repairs,
       project.PROJECT_CODE AS depends_on_project_code, p.PIPELINE_CODE AS depends_on_pipeline_code,
       t.TASK_CODE AS depends_on_task_code, (p.PROJECT_ID = :project_id) AS same_project,
       CASE WHEN p.PROJECT_ID=:project_id THEN p.PIPELINE_CODE || '.' || t.TASK_CODE ELSE project.PROJECT_CODE || '.' || p.PIPELINE_CODE || '.' || t.TASK_CODE END AS depends_on_label
FROM CFG_TASK_DEPENDENCY d
JOIN CFG_PIPELINES c ON c.PIPELINE_ID = d.PIPELINE_ID
JOIN CFG_TASKS t ON t.TASK_ID = d.DEPENDS_ON_TASK_ID
JOIN CFG_PIPELINES p ON p.PIPELINE_ID = d.DEPENDS_ON_PIPELINE_ID
JOIN CFG_PROJECTS project ON project.PROJECT_ID=p.PROJECT_ID
WHERE d.TASK_ID = :task_id AND d.ACTIVE_FLAG = 'Y' AND d.DEPENDS_ON_PIPELINE_ID <> d.PIPELINE_ID
ORDER BY d.TASK_DEPENDENCY_ID
