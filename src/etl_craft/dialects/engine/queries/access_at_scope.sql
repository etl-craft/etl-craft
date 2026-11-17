-- Bindings at exactly one reach: the deployment, one environment type, or one project.
SELECT x.BINDING_ID AS grant_id,g.GROUP_NAME AS group_name,a.ACCOUNT_NAME AS account,
x.GRANTEE_ROLE AS audience,x.PIPELINE_CODE AS pipeline,x.TAG AS tag,x.ROLE_NAME AS role,
x.ACTION_NAME AS action,x.ACTIVE_FLAG AS active_flag
FROM CFG_ACCESS_BINDINGS x LEFT JOIN CFG_GROUPS g ON g.GROUP_ID=x.GROUP_ID
LEFT JOIN CFG_ACCOUNTS a ON a.ACCOUNT_ID=x.ACCOUNT_ID
WHERE COALESCE(x.PROJECT_ID,0)=COALESCE(CAST(:project_id AS bigint),0)
AND COALESCE(x.ENVIRONMENT_TYPE,'')=COALESCE(CAST(:environment AS text),'')
ORDER BY x.BINDING_ID
