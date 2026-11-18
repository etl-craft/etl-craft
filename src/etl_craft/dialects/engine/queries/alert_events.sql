WITH candidates AS (
 SELECT r.PIPELINE_RUN_ID AS source_run_id,r.RUN_DATE AS run_date,
        'run:' || CAST(r.PIPELINE_RUN_ID AS varchar) AS identity,
        CAST(NULL AS bigint) AS source_task_id,CAST(NULL AS bigint) AS source_attempt_id,
        r.END_DATE AS event_at
 FROM AUD_PIPELINES_RUN_LOG r
 WHERE r.PIPELINE_ID=:pipeline_id AND
 ((:selector='FAILURE' AND r.STATUS='FAILED') OR (:selector='SLA_BREACH' AND r.SLA_STATUS='BREACHED')
  OR (:selector IN ('SUCCESS','COMPLETED_WITH_ERRORS') AND r.STATUS='SUCCESS' AND
      (CASE WHEN r.SLA_STATUS='BREACHED' OR EXISTS (
         SELECT 1 FROM AUD_TASK_RUN_LOG t JOIN CFG_TASKS k ON k.TASK_ID=t.TASK_ID
         WHERE t.PIPELINE_RUN_ID=r.PIPELINE_RUN_ID AND k.HANDLER<>'ALERT' AND
         (t.STATUS<>'SUCCESS' OR t.ERROR_MESSAGE IS NOT NULL OR
          t.ATTEMPT_COUNT>1))
       THEN 'COMPLETED_WITH_ERRORS' ELSE 'SUCCESS' END)=:selector))
 UNION ALL
 SELECT r.PIPELINE_RUN_ID AS source_run_id,r.RUN_DATE AS run_date,
        'attempt:' || CAST(a.ATTEMPT_ID AS varchar) AS identity,
        t.TASK_ID AS source_task_id,a.ATTEMPT_ID AS source_attempt_id,a.ENDED_AT AS event_at
 FROM AUD_TASK_ATTEMPTS a JOIN AUD_TASK_RUN_LOG t ON t.TASK_RUN_ID=a.TASK_RUN_ID
 JOIN AUD_PIPELINES_RUN_LOG r ON r.PIPELINE_RUN_ID=t.PIPELINE_RUN_ID
 WHERE r.PIPELINE_ID=:pipeline_id AND :selector='LOST' AND a.STATUS='LOST'
 UNION ALL
 SELECT r.PIPELINE_RUN_ID AS source_run_id,r.RUN_DATE AS run_date,
        'gate:' || CAST(r.PIPELINE_RUN_ID AS varchar) || ':' || COALESCE(CAST(g.TASK_ID AS varchar),'pipeline') || ':' || g.WAIT_KIND || ':' || CAST(g.FIRST_CHECK_AT AS varchar) AS identity,
        g.TASK_ID AS source_task_id,CAST(NULL AS bigint) AS source_attempt_id,
        CAST(NULL AS timestamptz) AS event_at
 FROM AUD_GATE_WAITS g JOIN AUD_PIPELINES_RUN_LOG r ON r.PIPELINE_RUN_ID=g.PIPELINE_RUN_ID
 WHERE r.PIPELINE_ID=:pipeline_id AND :selector LIKE 'GATE_WAIT_OVER_%'
 AND r.STATUS IN ('QUEUED','IN-PROGRESS') AND g.NEXT_CHECK_AT IS NOT NULL AND g.FIRST_CHECK_AT<=:gate_before
)
SELECT c.source_run_id AS source_run_id,c.run_date AS run_date,
       :event_prefix || c.identity AS event_id,c.source_task_id AS source_task_id,c.source_attempt_id AS source_attempt_id
FROM candidates c
WHERE (c.event_at IS NULL OR c.event_at>=:since)
AND NOT EXISTS (SELECT 1 FROM AUD_ALERT_DELIVERIES d WHERE d.CHANNEL_ID=:channel_id AND d.EVENT_ID=:event_prefix || c.identity AND d.STATUS='ADMITTED')
AND NOT EXISTS (SELECT 1 FROM AUD_ALERT_DELIVERIES d WHERE d.PIPELINE_RUN_ID=c.source_run_id AND d.STATUS='ADMITTED')
AND NOT EXISTS (SELECT 1 FROM AUD_PIPELINES_RUN_LOG delivered WHERE delivered.PIPELINE_ID=:pipeline_id AND delivered.RUN_KEY='alert:' || :event_prefix || c.identity)
ORDER BY c.source_run_id,c.identity LIMIT 100
