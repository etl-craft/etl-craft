SELECT STARTED_AT AS removed_at
FROM AUD_ACTIONS
WHERE PIPELINE_ID IS NULL AND PROJECT_ID = :project_id AND COMMAND = :command AND OUTCOME = :outcome
  AND STARTED_AT > :ended_at
  AND json_extract(ARGUMENTS, '$.warehouse_retention') = :target_name
  AND CAST(json_extract(ARGUMENTS, ('$.counts."' || :reject_table || '"')) AS bigint) > 0
ORDER BY STARTED_AT DESC
LIMIT 1
