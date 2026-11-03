SELECT e.EVENT_ID AS event_id,e.KEY_HASH AS key_hash,e.COLUMN_NAMES AS column_names
FROM AUD_PROTECTION_EVENTS e WHERE e.PROJECT_ID=:project_id AND e.TARGET_ID=:target
 AND e.REQUEST_ID=:request_id AND e.STATUS='PENDING' AND e.EVENT_ID>:cursor
 AND e.KEY_HASH IN (SELECT value AS key_hash FROM jsonb_array_elements_text(CAST(:key_hashes AS jsonb)) AS keys(value))
ORDER BY e.EVENT_ID LIMIT :page_size
