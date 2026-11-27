SELECT START_DATE AS start_date, END_DATE AS end_date,
       SOURCE_COUNT AS source_count, TARGET_COUNT AS target_count,
       INSERT_COUNT AS insert_count, UPDATE_COUNT AS update_count,
       DELETE_COUNT AS delete_count, ROWS_WRITTEN AS rows_written,
       REJECT_COUNT AS reject_count, DUPLICATE_COUNT AS duplicate_count
FROM AUD_TASK_RUN_LOG
WHERE TASK_ID = :task_id AND STATUS = :status
ORDER BY END_DATE DESC NULLS LAST, TASK_RUN_ID DESC
LIMIT 20
