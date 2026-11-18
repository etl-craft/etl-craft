-- Projects the principal sees, with its project-wide level. Any binding in a project makes it
-- visible, a pipeline or tag binding included; the level counts project-wide bindings, so a
-- visible project holds at least CAN_VIEW and only a project-wide grant raises it further.
WITH eligible AS ({{permission_eligible}}), project_levels AS (
 SELECT p.PROJECT_ID AS project_id,p.PROJECT_CODE AS project_code,
 CASE WHEN :role='admin' THEN 4 ELSE COALESCE(MAX(CASE
  WHEN e.grant_id IS NULL THEN 0
  WHEN e.pipeline_code IS NOT NULL OR e.tag IS NOT NULL OR e.custom=1 THEN 1
  ELSE CASE e.permission WHEN 'CAN_MANAGE' THEN 4 WHEN 'CAN_RUN' THEN 3 WHEN 'CAN_UPLOAD' THEN 2
   ELSE 1 END END),0) END AS level
 FROM CFG_PROJECTS p LEFT JOIN eligible e ON e.project_id=p.PROJECT_ID
 WHERE p.ACTIVE_FLAG='Y' AND (CAST(:project_id AS bigint) IS NULL OR p.PROJECT_ID=:project_id)
 GROUP BY p.PROJECT_ID,p.PROJECT_CODE
), selected_projects AS (
 SELECT project_id,project_code,level FROM project_levels WHERE level>0
 AND (CAST(:after_project AS text) IS NULL OR project_code>:after_project)
 ORDER BY project_code LIMIT :project_limit
)
SELECT project_id,project_code,level FROM selected_projects
