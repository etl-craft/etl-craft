-- Active bindings that reach this principal: its account, an active group it belongs to or signed
-- in with, or an audience its deployment role includes. The one principal match every access
-- decision and visibility filter uses.
SELECT b.BINDING_ID AS binding_id,b.PROJECT_ID AS project_id,b.ENVIRONMENT_TYPE AS environment,
b.PIPELINE_CODE AS pipeline_code,b.TAG AS tag,b.ROLE_NAME AS role_name,b.ACTION_NAME AS action_name,
CASE WHEN b.GROUP_ID IS NOT NULL THEN 'group:' || CAST(b.GROUP_ID AS text)
     WHEN b.ACCOUNT_ID IS NOT NULL THEN 'account:' || a.ACCOUNT_NAME
     ELSE 'role:' || b.GRANTEE_ROLE END AS source,
CASE WHEN b.GROUP_ID IS NOT NULL THEN 'group:' || g.GROUP_NAME
     WHEN b.ACCOUNT_ID IS NOT NULL THEN 'account:' || a.ACCOUNT_NAME
     ELSE 'audience:' || b.GRANTEE_ROLE END AS principal
FROM CFG_ACCESS_BINDINGS b
LEFT JOIN CFG_ACCOUNTS a ON a.ACCOUNT_ID=b.ACCOUNT_ID
LEFT JOIN CFG_GROUPS g ON g.GROUP_ID=b.GROUP_ID
WHERE b.ACTIVE_FLAG='Y'
AND ((a.ACCOUNT_NAME=:account AND a.ACTIVE_FLAG='Y')
 OR (b.GRANTEE_ROLE='viewer' AND :role IN ('viewer','operator','developer','admin'))
 OR (b.GRANTEE_ROLE='operator' AND :role IN ('operator','developer','admin'))
 OR (b.GRANTEE_ROLE='developer' AND :role IN ('developer','admin'))
 OR (g.ACTIVE_FLAG='Y' AND (EXISTS (
   SELECT 1 AS member FROM CFG_GROUP_MEMBERS m JOIN CFG_ACCOUNTS u ON u.ACCOUNT_ID=m.ACCOUNT_ID
   WHERE m.GROUP_ID=g.GROUP_ID AND m.ACTIVE_FLAG='Y' AND u.ACCOUNT_NAME=:account AND u.ACTIVE_FLAG='Y')
   OR g.GROUP_ID IN (SELECT CAST(value AS bigint) AS group_id FROM json_each(:sso_group_ids)))))
