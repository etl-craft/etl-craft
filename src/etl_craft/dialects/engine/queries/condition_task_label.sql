-- One task named PROJECT.PIPELINE.TASK, for a cycle message through another project.
SELECT pr.PROJECT_CODE || '.' || p.PIPELINE_CODE || '.' || t.TASK_CODE AS label
FROM CFG_TASKS t
JOIN CFG_PIPELINES p ON p.PIPELINE_ID = t.PIPELINE_ID
JOIN CFG_PROJECTS pr ON pr.PROJECT_ID = p.PROJECT_ID
WHERE t.TASK_ID = :task_id
