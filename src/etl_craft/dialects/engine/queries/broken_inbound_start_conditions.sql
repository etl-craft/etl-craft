SELECT up.PIPELINE_CODE AS upstream_pipeline, NULL AS upstream_task,
       dp.PROJECT_ID AS downstream_project_id, pr.PROJECT_CODE AS downstream_project,
       dp.PIPELINE_ID AS downstream_pipeline_id, dp.PIPELINE_CODE AS downstream_pipeline,
       NULL AS downstream_task
FROM CFG_PIPELINES up
JOIN CFG_PIPELINE_DEPENDENCY d ON d.DEPENDS_ON_PIPELINE_ID = up.PIPELINE_ID
JOIN CFG_PIPELINES dp ON dp.PIPELINE_ID = d.PIPELINE_ID AND dp.ACTIVE_FLAG = 'Y'
JOIN CFG_PROJECTS pr ON pr.PROJECT_ID = dp.PROJECT_ID AND pr.ACTIVE_FLAG = 'Y'
WHERE up.PROJECT_ID = :project_id AND dp.PROJECT_ID <> :project_id
  AND d.ACTIVE_FLAG = 'Y' AND up.ACTIVE_FLAG = 'N'
