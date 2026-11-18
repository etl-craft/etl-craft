-- The principal's bindings expanded onto the projects they apply to: a deployment binding covers
-- every project, an environment binding every project of that environment type. Built-in CAN_*
-- rows keep their level; a custom role or single action implies CAN_VIEW on its environment,
-- project, pipeline or tag, never deployment-wide, so a deployment-only role reveals no project.
SELECT x.binding_id AS grant_id,pj.PROJECT_ID AS project_id,x.pipeline_code AS pipeline_code,
x.tag AS tag,
CASE WHEN x.role_name IN ('CAN_VIEW','CAN_UPLOAD','CAN_RUN','CAN_MANAGE') THEN x.role_name ELSE 'CAN_VIEW' END AS permission,
CASE WHEN x.role_name IN ('CAN_VIEW','CAN_UPLOAD','CAN_RUN','CAN_MANAGE') THEN 0 ELSE 1 END AS custom,
x.source AS source
FROM ({{access_principal}}) x LEFT JOIN CFG_ROLES r ON r.ROLE_NAME=x.role_name
JOIN CFG_PROJECTS pj ON pj.PROJECT_ID=x.project_id
 OR (x.project_id IS NULL AND (x.environment IS NULL OR x.environment=pj.ENVIRONMENT_TYPE))
WHERE (x.action_name IS NOT NULL OR r.ACTIVE_FLAG='Y')
AND (x.role_name IN ('CAN_VIEW','CAN_UPLOAD','CAN_RUN','CAN_MANAGE')
 OR x.project_id IS NOT NULL OR x.environment IS NOT NULL)
AND (CAST(:project_id AS bigint) IS NULL OR pj.PROJECT_ID=:project_id)
