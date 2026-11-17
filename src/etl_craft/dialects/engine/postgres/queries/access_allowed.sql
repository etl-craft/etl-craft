-- Custom bindings of this principal that include the action, on the deployment, the project's
-- environment type, or the project (any pipeline or tag narrowing is returned for the caller).
SELECT b.BINDING_ID AS binding_id,b.PROJECT_ID AS project_id,b.ENVIRONMENT_TYPE AS environment,
b.PIPELINE_CODE AS pipeline_code,b.TAG AS tag,COALESCE(b.ROLE_NAME,b.ACTION_NAME) AS granted,
CASE WHEN b.GROUP_ID IS NOT NULL THEN 'group:' || g.GROUP_NAME
     WHEN b.ACCOUNT_ID IS NOT NULL THEN 'account:' || a.ACCOUNT_NAME
     ELSE 'audience:' || b.GRANTEE_ROLE END AS principal
FROM CFG_ACCESS_BINDINGS b
LEFT JOIN CFG_ROLES r ON r.ROLE_NAME=b.ROLE_NAME AND r.ACTIVE_FLAG='Y' AND r.BUILT_IN_FLAG='N'
LEFT JOIN CFG_ACCOUNTS a ON a.ACCOUNT_ID=b.ACCOUNT_ID
LEFT JOIN CFG_GROUPS g ON g.GROUP_ID=b.GROUP_ID
WHERE b.ACTIVE_FLAG='Y'
AND (b.ACTION_NAME=:action OR EXISTS (SELECT 1 AS held FROM CFG_ROLE_ACTIONS ra
 WHERE ra.ROLE_ID=r.ROLE_ID AND ra.ACTIVE_FLAG='Y' AND ra.ACTION_NAME=:action))
AND (b.PROJECT_ID=CAST(:project_id AS bigint) OR (b.PROJECT_ID IS NULL AND (b.ENVIRONMENT_TYPE IS NULL
 OR b.ENVIRONMENT_TYPE=(SELECT pj.ENVIRONMENT_TYPE AS environment FROM CFG_PROJECTS pj WHERE pj.PROJECT_ID=:project_id))))
AND ((a.ACCOUNT_NAME=:account AND a.ACTIVE_FLAG='Y')
 OR (b.GRANTEE_ROLE='viewer' AND :role IN ('viewer','operator','developer','admin'))
 OR (b.GRANTEE_ROLE='operator' AND :role IN ('operator','developer','admin'))
 OR (b.GRANTEE_ROLE='developer' AND :role IN ('developer','admin'))
 OR (g.ACTIVE_FLAG='Y' AND (EXISTS (
   SELECT 1 AS member FROM CFG_GROUP_MEMBERS m JOIN CFG_ACCOUNTS u ON u.ACCOUNT_ID=m.ACCOUNT_ID
   WHERE m.GROUP_ID=g.GROUP_ID AND m.ACTIVE_FLAG='Y' AND u.ACCOUNT_NAME=:account AND u.ACTIVE_FLAG='Y')
   OR g.GROUP_ID IN (SELECT CAST(value AS bigint) AS group_id FROM jsonb_array_elements_text(CAST(:sso_group_ids AS jsonb))))))
ORDER BY b.BINDING_ID
