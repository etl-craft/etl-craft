INSERT INTO CFG_ACCESS_BINDINGS
(PROJECT_ID,ENVIRONMENT_TYPE,GROUP_ID,ACCOUNT_ID,GRANTEE_ROLE,PIPELINE_CODE,TAG,ROLE_NAME,ACTION_NAME,ACTIVE_FLAG)
VALUES (:project_id,:environment,:group_id,:account_id,:grantee_role,:pipeline,:tag,:permission,:action,'Y')
