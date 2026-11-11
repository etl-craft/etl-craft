SELECT clock_timestamp() AS observed_now, a.ATTEMPT_ID AS attempt_id, a.STATUS AS status, a.OWNER_ID AS owner_id,
       a.HOST AS host, a.PID AS pid, a.PROCESS_START AS process_start,
       a.LEASE_EXPIRES_AT AS lease_expires_at, a.CLAIMED_AT AS claimed_at,
       a.AGENT_INSTANCE_ID AS agent_instance_id,
       g.INSTANCE_ID AS registered_instance_id, g.HOST AS registered_host,
       g.STARTED_AT AS registered_at, g.STATUS AS registered_status,
       g.HEARTBEAT_AT AS registered_heartbeat,
       token.TOKEN_SHA256 AS token_digest,
       EXISTS (SELECT 1 AS present FROM AUD_ATTEMPT_ACKNOWLEDGEMENTS e
               WHERE e.ATTEMPT_ID = a.ATTEMPT_ID AND e.KIND = 'PROCESS') AS process_observed
FROM AUD_TASK_ATTEMPTS a
LEFT JOIN AUD_AGENTS g ON CAST(g.AGENT_ID AS varchar) = a.OWNER_ID
LEFT JOIN CFG_API_TOKENS token ON token.TOKEN_ID = g.AGENT_ID
WHERE a.ATTEMPT_ID = :attempt_id
FOR UPDATE OF a
