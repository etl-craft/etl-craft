SELECT
 (CAST(:attempt_id AS bigint) IS NULL OR EXISTS (
 SELECT 1 AS live FROM AUD_TASK_ATTEMPTS a WHERE a.ATTEMPT_ID=:attempt_id
 AND a.TASK_RUN_ID=:task_run_id AND a.OWNER_ID=:owner
 AND a.STATUS IN ('CLAIMED','RUNNING') AND a.LEASE_EXPIRES_AT>(strftime('%Y-%m-%d %H:%M:%f', 'now') || '000+00:00')
 )) AS live_attempt,
 EXISTS (SELECT 1 AS owned FROM AUD_RESOURCE_LOCKS l WHERE l.LOCK_KEY=:key
 AND l.HOLDER_ID=:holder AND l.OWNER_ID=:lock_owner AND l.LEASE_EXPIRES_AT>(strftime('%Y-%m-%d %H:%M:%f', 'now') || '000+00:00')) AS lock_owned
