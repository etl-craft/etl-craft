-- PostgreSQL only: agent operations require cluster execution.
SELECT g.AGENT_ID AS agent_id,g.POOL AS pool,g.HOST AS host,g.VERSION AS version,
g.PYTHON_SLOTS AS python_slots,g.WAREHOUSE_SLOTS AS warehouse_slots,g.STATUS AS status,
g.STARTED_AT AS started_at,g.HEARTBEAT_AT AS heartbeat_at,g.RESOURCE_REPORT AS resource_report,
account.ACCOUNT_ID AS credential_account_id,account.ACCOUNT_NAME AS credential_account_name,
EXISTS (SELECT 1 FROM CFG_API_TOKENS t JOIN CFG_ACCOUNTS a ON a.ACCOUNT_ID=t.ACCOUNT_ID
        WHERE t.TOKEN_ID=g.AGENT_ID AND t.TOKEN_KIND='AGENT' AND t.PROJECT_ID IS NULL
        AND t.ACTIVE_FLAG='Y' AND a.ACTIVE_FLAG='Y' AND t.REVOKED_AT IS NULL
        AND (t.EXPIRES_AT IS NULL OR t.EXPIRES_AT>clock_timestamp())) AS credential_live
FROM AUD_AGENTS g JOIN CFG_API_TOKENS credential ON credential.TOKEN_ID=g.AGENT_ID
JOIN CFG_ACCOUNTS account ON account.ACCOUNT_ID=credential.ACCOUNT_ID
WHERE g.AGENT_ID=:agent_id
