-- Every active pipeline, by code.
SELECT PIPELINE_ID AS pipeline_id, PIPELINE_CODE AS pipeline_code, PIPELINE_NAME AS pipeline_name, DESCRIPTION AS description,
       STEWARDABLE_FLAG AS stewardable_flag, ACTIVE_FLAG AS active_flag,
       REFRESH_TYPE AS refresh_type, RUN_SCHEDULE AS run_schedule, AUTO_RESTART_CONDITION AS auto_restart_condition, SLA_IN_HOURS AS sla_in_hours, PIPELINE_PARAMETERS AS pipeline_parameters
FROM CFG_PIPELINES
WHERE ACTIVE_FLAG = 'Y' AND PROJECT_ID=:project_id
ORDER BY PIPELINE_CODE
