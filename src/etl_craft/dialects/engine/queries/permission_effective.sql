-- Each visible project, then each of its pipelines with the principal's level there: the highest
-- level among its bindings that reach the pipeline, project-wide, on the pipeline itself or on one
-- of its tags. Grants only add: a pipeline or tag binding never hides a pipeline from anyone. A
-- custom role or single action reaching a pipeline shows it at CAN_VIEW.
WITH eligible AS ({{permission_eligible}}), selected_projects AS ({{permission_projects}}),
reaching AS (
 SELECT p.PIPELINE_ID AS pipeline_id,e.permission AS permission,e.source AS source
 FROM CFG_PIPELINES p JOIN selected_projects pr ON pr.project_id=p.PROJECT_ID
 JOIN eligible e ON e.project_id=p.PROJECT_ID
 AND ((e.pipeline_code IS NULL AND e.tag IS NULL) OR e.pipeline_code=p.PIPELINE_CODE
  OR e.tag IN (SELECT value AS tag FROM json_each(COALESCE(p.PIPELINE_PARAMETERS,'{}'),'$.TAGS')))
), pipeline_levels AS (
 SELECT p.PIPELINE_ID AS pipeline_id,p.PIPELINE_CODE AS pipeline_code,pr.project_id AS project_id,
 pr.project_code AS project_code,
 CASE WHEN :role='admin' THEN 4 ELSE COALESCE((SELECT MAX(CASE x.permission WHEN 'CAN_MANAGE' THEN 4
  WHEN 'CAN_RUN' THEN 3 WHEN 'CAN_UPLOAD' THEN 2 ELSE 1 END) AS level
  FROM reaching x WHERE x.pipeline_id=p.PIPELINE_ID),0) END AS level,
 COALESCE((SELECT json_group_array(x.source) AS sources FROM reaching x
  WHERE x.pipeline_id=p.PIPELINE_ID),'[]') AS sources
 FROM CFG_PIPELINES p JOIN selected_projects pr ON pr.project_id=p.PROJECT_ID
)
SELECT project_id,project_code,NULL AS pipeline_id,NULL AS pipeline_code,level,'[]' AS sources
FROM selected_projects
UNION ALL SELECT project_id,project_code,pipeline_id,pipeline_code,level,sources FROM pipeline_levels
