-- Active declared target columns of one task, not inferred warehouse columns.
SELECT c.COLUMN_NAME AS column_name FROM CFG_TASKS t
JOIN CFG_COLUMNS c ON c.TABLE_ID=t.TARGET_TABLE_ID
JOIN CFG_TABLES o ON o.TABLE_ID=c.TABLE_ID
WHERE t.TASK_ID=:task_id AND c.ACTIVE_FLAG='Y' AND o.ACTIVE_FLAG='Y' AND t.TARGET_ACTIVE_FLAG='Y'
