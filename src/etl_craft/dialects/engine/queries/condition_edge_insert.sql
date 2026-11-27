INSERT INTO CFG_TASK_DEPENDENCY (PIPELINE_ID, TASK_ID, DEPENDS_ON_PIPELINE_ID, DEPENDS_ON_TASK_ID)
VALUES (:pipeline_id, :task_id, :depends_on_pipeline_id, :depends_on_task_id)
