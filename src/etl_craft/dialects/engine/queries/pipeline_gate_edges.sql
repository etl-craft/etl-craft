-- The active derived start edges of :pipeline_id, using the consuming pipeline's repair policy.
SELECT d.PIPELINE_DEPENDENCY_ID AS pipeline_dependency_id,
       d.DEPENDS_ON_PIPELINE_ID AS depends_on_pipeline_id,
       p.PIPELINE_CODE AS upstream_code, project.PROJECT_CODE AS upstream_project,
       (p.PROJECT_ID = c.PROJECT_ID) AS same_project,
       (c.CONSUME_REPAIRS = 'Y') AS consume_repairs
FROM CFG_PIPELINE_DEPENDENCY d
JOIN CFG_PIPELINES p ON p.PIPELINE_ID = d.DEPENDS_ON_PIPELINE_ID
JOIN CFG_PIPELINES c ON c.PIPELINE_ID = d.PIPELINE_ID
JOIN CFG_PROJECTS project ON project.PROJECT_ID = p.PROJECT_ID
WHERE d.PIPELINE_ID = :pipeline_id AND d.ACTIVE_FLAG = 'Y'
ORDER BY d.PIPELINE_DEPENDENCY_ID
