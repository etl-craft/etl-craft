SELECT RUN_DATE AS logical_date, START_DATE AS start_date, END_DATE AS end_date,
STATUS AS status FROM AUD_PIPELINES_RUN_LOG WHERE PIPELINE_RUN_ID = :pipeline_run_id
