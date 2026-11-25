-- Changes made to the listed runs, oldest first.
SELECT i.INTERVENTION_ID AS intervention_id, i.PIPELINE_RUN_ID AS pipeline_run_id,
       t.TASK_CODE AS task_code, i.ACTION AS action, i.FROM_STATUS AS from_status,
       i.TO_STATUS AS to_status, i.TARGET_COUNT AS target_count,
       i.PREVIOUS_MESSAGE AS previous_message, i.REASON AS reason,
       i.REQUESTED_BY AS requested_by, i.REQUESTED_AT AS requested_at, i.ITEM_KEY AS item_key
FROM AUD_RUN_INTERVENTIONS i
LEFT JOIN CFG_TASKS t ON t.TASK_ID = i.TASK_ID
WHERE i.PIPELINE_RUN_ID IN :run_ids
ORDER BY i.INTERVENTION_ID
