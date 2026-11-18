-- Every action the principal holds through its bindings, built-in and custom roles alike, with
-- where each binding applies: the deployment, the selected project's environment type, the
-- project, or one of its pipelines or tags.
SELECT x.binding_id AS binding_id,x.project_id AS project_id,x.environment AS environment,
x.pipeline_code AS pipeline_code,x.tag AS tag,x.principal AS principal,
COALESCE(x.role_name,x.action_name) AS granted,COALESCE(ra.ACTION_NAME,x.action_name) AS action_name
FROM ({{access_principal}}) x
LEFT JOIN CFG_ROLES r ON r.ROLE_NAME=x.role_name AND r.ACTIVE_FLAG='Y'
LEFT JOIN CFG_ROLE_ACTIONS ra ON ra.ROLE_ID=r.ROLE_ID AND ra.ACTIVE_FLAG='Y'
WHERE COALESCE(ra.ACTION_NAME,x.action_name) IS NOT NULL
AND (x.project_id=CAST(:project_id AS bigint) OR (x.project_id IS NULL AND (x.environment IS NULL
 OR x.environment=(SELECT pj.ENVIRONMENT_TYPE AS environment FROM CFG_PROJECTS pj
  WHERE pj.PROJECT_ID=CAST(:project_id AS bigint)))))
ORDER BY x.binding_id
