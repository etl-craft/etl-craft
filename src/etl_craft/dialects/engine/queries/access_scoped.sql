-- Bindings expanded onto the projects they apply to: a deployment binding covers every project,
-- an environment binding every project of that environment type. Built-in CAN_* rows keep their
-- level; a custom role or single action implies CAN_VIEW on its environment, project, pipeline or
-- tag, never deployment-wide, so a deployment-only role does not reveal projects.
SELECT b.BINDING_ID AS binding_id,pj.PROJECT_ID AS project_id,b.PIPELINE_CODE AS pipeline_code,
b.TAG AS tag,b.GROUP_ID AS group_id,b.ACCOUNT_ID AS account_id,b.GRANTEE_ROLE AS grantee_role,
b.ROLE_NAME AS role_name,b.ACTION_NAME AS action_name,
CASE WHEN b.ROLE_NAME IN ('CAN_VIEW','CAN_UPLOAD','CAN_RUN','CAN_MANAGE') THEN 0 ELSE 1 END AS custom,
CASE WHEN b.ROLE_NAME IN ('CAN_VIEW','CAN_UPLOAD','CAN_RUN','CAN_MANAGE') THEN b.ROLE_NAME ELSE 'CAN_VIEW' END AS permission
FROM CFG_ACCESS_BINDINGS b LEFT JOIN CFG_ROLES r ON r.ROLE_NAME=b.ROLE_NAME
JOIN CFG_PROJECTS pj ON pj.PROJECT_ID=b.PROJECT_ID
 OR (b.PROJECT_ID IS NULL AND (b.ENVIRONMENT_TYPE IS NULL OR b.ENVIRONMENT_TYPE=pj.ENVIRONMENT_TYPE))
WHERE b.ACTIVE_FLAG='Y' AND (b.ACTION_NAME IS NOT NULL OR r.ACTIVE_FLAG='Y') AND (b.ROLE_NAME IN ('CAN_VIEW','CAN_UPLOAD','CAN_RUN','CAN_MANAGE')
 OR b.PROJECT_ID IS NOT NULL OR b.ENVIRONMENT_TYPE IS NOT NULL)
