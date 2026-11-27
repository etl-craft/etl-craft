SELECT p.PIPELINE_ID AS pipeline_id, pr.PROJECT_ID AS project_id,
       pr.PROJECT_CODE AS project_code, p.PIPELINE_CODE AS pipeline_code,
       p.START_CONDITION AS start_condition,
       CASE WHEN p.ACTIVE_FLAG = 'Y' AND pr.ACTIVE_FLAG = 'Y' THEN 1 ELSE 0 END AS active
FROM CFG_PIPELINES p JOIN CFG_PROJECTS pr ON pr.PROJECT_ID = p.PROJECT_ID
