-- PostgreSQL only: serialize deployment capacity before selecting queued pipelines.
WITH hosts AS (
    SELECT g.AGENT_ID AS agent_id FROM CFG_POOLS p CROSS JOIN AUD_AGENTS g
    WHERE p.POOL_NAME='default' AND g.RESOURCE_REPORT\:\:jsonb->>'node_id'=(
        SELECT selected.RESOURCE_REPORT\:\:jsonb->>'node_id' FROM AUD_AGENTS selected
        WHERE selected.AGENT_ID=:agent_id
    ) ORDER BY g.AGENT_ID FOR UPDATE OF p,g
), queued AS (
    SELECT DISTINCT r.PIPELINE_ID AS pipeline_id FROM AUD_TASK_ATTEMPTS a
    JOIN AUD_TASK_RUN_LOG t ON t.TASK_RUN_ID=a.TASK_RUN_ID
    JOIN AUD_PIPELINES_RUN_LOG r ON r.PIPELINE_RUN_ID=t.PIPELINE_RUN_ID
    WHERE a.STATUS='QUEUED' AND a.OWNER_ID IS NULL
    AND a.POOL=(SELECT POOL FROM AUD_AGENTS WHERE AGENT_ID=:agent_id)
)
SELECT q.pipeline_id AS pipeline_id FROM queued q
CROSS JOIN (SELECT count(*) AS count FROM hosts) locked
WHERE locked.count>0 ORDER BY q.pipeline_id
