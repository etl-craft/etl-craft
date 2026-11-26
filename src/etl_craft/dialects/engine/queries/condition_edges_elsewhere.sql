-- The active derived task edges of every other project, named PROJECT.PIPELINE.TASK, so a
-- project's own edges can be checked for a cycle through them.
SELECT tp.PROJECT_CODE || '.' || p.PIPELINE_CODE || '.' || t.TASK_CODE AS task_label,
       up.PROJECT_CODE || '.' || u_p.PIPELINE_CODE || '.' || u.TASK_CODE AS upstream_label
FROM CFG_TASK_DEPENDENCY d
JOIN CFG_TASKS t ON t.TASK_ID = d.TASK_ID
JOIN CFG_PIPELINES p ON p.PIPELINE_ID = t.PIPELINE_ID
JOIN CFG_PROJECTS tp ON tp.PROJECT_ID = p.PROJECT_ID
JOIN CFG_TASKS u ON u.TASK_ID = d.DEPENDS_ON_TASK_ID
JOIN CFG_PIPELINES u_p ON u_p.PIPELINE_ID = u.PIPELINE_ID
JOIN CFG_PROJECTS up ON up.PROJECT_ID = u_p.PROJECT_ID
WHERE d.ACTIVE_FLAG = 'Y' AND p.PROJECT_ID <> :project_id
