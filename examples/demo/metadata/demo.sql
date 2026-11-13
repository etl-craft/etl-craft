CREATE TEMP TABLE task_targets (PIPELINE_CODE VARCHAR NOT NULL,TASK_CODE VARCHAR NOT NULL,
    SCHEMA_NAME VARCHAR NOT NULL,TABLE_NAME VARCHAR NOT NULL);
INSERT INTO task_targets (PIPELINE_CODE,TASK_CODE,SCHEMA_NAME,TABLE_NAME) VALUES
    ('SOURCE_A','land','lnd','client_alpha'),
    ('SOURCE_A','setup_prs','prs','alpha_interactions'),
    ('SOURCE_A','parse','prs','alpha_interactions'),
    ('SOURCE_A','purge_test_calls','prs','alpha_interactions'),
    ('SOURCE_B','land','lnd','client_beta'),
    ('SOURCE_B','setup_prs','prs','beta_interactions'),
    ('SOURCE_B','parse','prs','beta_interactions'),
    ('DEMO','land_agents','lnd','agents'),
    ('DEMO','agents','ds','agents'),
    ('DEMO','retire_agents','ds','agents'),
    ('DEMO','setup_agent_history','cdc','agent_history'),
    ('DEMO','agent_history','cdc','agent_history'),
    ('DEMO','interactions','pre_dm','interactions'),
    ('DEMO','setup_fact','dm','support_fact'),
    ('DEMO','fact','dm','support_fact'),
    ('DEMO','area_summary','dm','area_summary'),
    ('DEMO','source_counts','pre_dm','source_counts'),
    ('DEMO','drop_source_counts','pre_dm','source_counts');
INSERT INTO CFG_TABLES (SCHEMA_NAME,TABLE_NAME)
SELECT DISTINCT v.SCHEMA_NAME,v.TABLE_NAME FROM task_targets v
WHERE NOT EXISTS (SELECT 1 FROM CFG_TABLES o WHERE o.CATALOG_NAME IS NULL
    AND o.SCHEMA_NAME=v.SCHEMA_NAME AND o.TABLE_NAME=v.TABLE_NAME);

-- The Small package demo's pipelines, tasks, dependencies and business rules, as CFG_ rows.
--
-- Load it into an Engine DB that `etl-craft setup` created. It runs as written on SQLite and on
-- PostgreSQL: every id is looked up by code, never written out.
--
--   SOURCE_A      land Client Alpha's interactions, parse them, purge its test calls
--   SOURCE_B       land Client Beta's events, parse them
--   DEMO        agents and support areas, then the support fact, its checks and summary,
--                     once both clients' pipelines have succeeded
--   EXPORT    a slow export: it overruns its time limit and its SLA
--   BACKFILL  a long backfill, for stopping a run and resuming it

INSERT INTO CFG_PIPELINES (PIPELINE_CODE, PIPELINE_NAME, DESCRIPTION, REFRESH_TYPE, SLA_IN_HOURS,
                           PIPELINE_PARAMETERS)
VALUES
    ('SOURCE_A', 'Client Alpha interactions',
     'Lands Client Alpha''s support interactions, as its desk exports them, and parses them into typed rows.',
     'INCREMENTAL', NULL, '{"TAGS": ["support", "client-alpha"]}'),
    ('SOURCE_B', 'Client Beta events',
     'Lands Client Beta''s support events and parses them into the shared shape.',
     'INCREMENTAL', NULL, '{"TAGS": ["support", "client-beta"]}'),
    ('DEMO', 'Support data mart',
     'Builds the support fact from every client''s interactions, with agents and support areas, checks it, and summarises it per area and team.',
     'INCREMENTAL', 2, '{"TAGS": ["support", "mart"]}'),
    ('EXPORT', 'Support export',
     'Exports the mart for a partner; it is slow, and overruns its time limit and its SLA.',
     'FULL', 0.0002, '{"EMAIL_RECIPIENTS": ["support-leads@example.com"]}'),
    ('BACKFILL', 'Support backfill',
     'A long backfill: stopped part way, it resumes where it stopped.',
     'FULL', NULL, NULL);
UPDATE CFG_PIPELINES SET MAX_PARALLEL_TASKS=4
WHERE PIPELINE_CODE IN ('SOURCE_A','SOURCE_B','DEMO','EXPORT','BACKFILL');


INSERT INTO CFG_TASKS (TASK_CODE, TASK_TYPE, PIPELINE_ID, HANDLER)
SELECT v.column2, v.column3, p.PIPELINE_ID, v.column4
FROM (VALUES
    ('SOURCE_A', 'land', 'INGESTION', 'PYTHON'),
    ('SOURCE_A', 'setup_prs', 'ETL', 'SQL'),
    ('SOURCE_A', 'parse', 'ETL', 'SQL'),
    ('SOURCE_A', 'purge_test_calls', 'ETL', 'SQL'),
    ('SOURCE_B', 'land', 'INGESTION', 'PYTHON'),
    ('SOURCE_B', 'setup_prs', 'ETL', 'SQL'),
    ('SOURCE_B', 'parse', 'ETL', 'SQL'),
    ('DEMO', 'land_agents', 'INGESTION', 'PYTHON'),
    ('DEMO', 'flaky_feed', 'INGESTION', 'PYTHON'),
    ('DEMO', 'on_failure', 'ETL', 'EMAIL_ALERT'),
    ('DEMO', 'agents', 'ETL', 'SQL'),
    ('DEMO', 'retire_agents', 'ETL', 'SQL'),
    ('DEMO', 'setup_agent_history', 'ETL', 'SQL'),
    ('DEMO', 'agent_history', 'ETL', 'SQL'),
    ('DEMO', 'interactions', 'ETL', 'SQL'),
    ('DEMO', 'setup_fact', 'ETL', 'SQL'),
    ('DEMO', 'fact', 'ETL', 'SQL'),
    ('DEMO', 'quality', 'ETL', 'BUSINESS_RULES'),
    ('DEMO', 'area_summary', 'ETL', 'SQL'),
    ('DEMO', 'source_counts', 'ETL', 'SQL'),
    ('DEMO', 'drop_source_counts', 'ETL', 'SQL'),
    ('DEMO', 'alert', 'ETL', 'EMAIL_ALERT'),
    ('EXPORT', 'export', 'ETL', 'PYTHON'),
    ('BACKFILL', 'prepare', 'ETL', 'PYTHON'),
    ('BACKFILL', 'backfill', 'ETL', 'PYTHON')
) v
JOIN CFG_PIPELINES p ON p.PIPELINE_CODE = v.column1;

-- area_summary runs once ANY of its dependencies has succeeded (either means the fact is there);
-- source_counts once 2 of its 3 have (any two mean the interactions are there).
UPDATE CFG_TASKS SET RUN_CONDITION = 'ANY'
WHERE TASK_CODE = 'area_summary'
  AND PIPELINE_ID = (SELECT PIPELINE_ID FROM CFG_PIPELINES WHERE PIPELINE_CODE = 'DEMO');
UPDATE CFG_TASKS SET RUN_CONDITION = 'N', RUN_CONDITION_COUNT = 2
WHERE TASK_CODE = 'source_counts'
  AND PIPELINE_ID = (SELECT PIPELINE_ID FROM CFG_PIPELINES WHERE PIPELINE_CODE = 'DEMO');

CREATE TEMP TABLE target_bindings (TASK_ID BIGINT NOT NULL,TABLE_ID BIGINT NOT NULL);
INSERT INTO target_bindings (TASK_ID,TABLE_ID)
SELECT t.TASK_ID,o.TABLE_ID FROM task_targets v
LEFT JOIN CFG_PIPELINES p ON p.PIPELINE_CODE=v.PIPELINE_CODE AND p.ACTIVE_FLAG='Y'
LEFT JOIN CFG_TASKS t ON t.PIPELINE_ID=p.PIPELINE_ID AND t.TASK_CODE=v.TASK_CODE AND t.ACTIVE_FLAG='Y'
LEFT JOIN CFG_TABLES o ON o.CATALOG_NAME IS NULL AND o.SCHEMA_NAME=v.SCHEMA_NAME
    AND o.TABLE_NAME=v.TABLE_NAME;
UPDATE CFG_TASKS SET TARGET_TABLE_ID=(SELECT b.TABLE_ID FROM target_bindings b WHERE b.TASK_ID=CFG_TASKS.TASK_ID)
WHERE TASK_ID IN (SELECT TASK_ID FROM target_bindings);
DROP TABLE target_bindings;
DROP TABLE task_targets;

INSERT INTO CFG_TASK_PARAMETERS (TASK_ID, PARAMETER_NAME, PARAMETER_VALUE)
SELECT t.TASK_ID, v.column3, v.column4
FROM (VALUES
    ('SOURCE_A', 'land', 'SCRIPT_KIND', 'INGESTION'),
    ('SOURCE_A', 'land', 'SCRIPT_FILE', 'python_scripts/alpha.py'),
    ('SOURCE_A', 'land', 'INPUT_PARAMS', '{"rows": 2}'),
    ('SOURCE_A', 'land', 'LINEAGE_SOURCE', 'client_alpha.support_interactions'),
    ('SOURCE_A', 'land', 'DOCUMENTATION', 'Lands the interactions Client Alpha''s desk exported since the last one loaded, every field as text.'),
    ('SOURCE_A', 'setup_prs', 'SQL_ACTION', 'SETUP_TABLE'),
    ('SOURCE_A', 'setup_prs', 'SELECT_QUERY', 'SELECT CAST(a.interaction_id AS BIGINT) AS interaction_id, a.agent_code, a.support_area, CAST(a.contact_date AS DATE) AS contact_date, a.status, CAST(a.duration_seconds AS INTEGER) AS handle_seconds, CAST(a.rating AS INTEGER) AS rating, CAST(0 AS BIGINT) AS parsed_by FROM lnd.client_alpha a WHERE 1 = 0'),
    ('SOURCE_A', 'parse', 'SQL_ACTION', 'APPEND_TABLE'),
    ('SOURCE_A', 'parse', 'SCRIPT_FILE', 'sql_scripts/prs_alpha.sql'),
    ('SOURCE_A', 'parse', 'PIPELINE_RUN_ID_SUBSTITUTION', 'true'),
    ('SOURCE_A', 'parse', 'DOCUMENTATION', 'Types Client Alpha''s landed interactions and appends the new ones, stamped with the run that parsed them.'),
    ('SOURCE_A', 'purge_test_calls', 'SQL_ACTION', 'DELETE_ROWS'),
    ('SOURCE_A', 'purge_test_calls', 'SELECT_QUERY', 'SELECT interaction_id FROM prs.alpha_interactions WHERE agent_code = ''TEST'''),
    ('SOURCE_A', 'purge_test_calls', 'MERGE_KEY', 'interaction_id'),
    ('SOURCE_A', 'purge_test_calls', 'HARD_DELETE', 'true'),
    ('SOURCE_B', 'land', 'SCRIPT_KIND', 'INGESTION'),
    ('SOURCE_B', 'land', 'SCRIPT_FILE', 'python_scripts/beta.py'),
    ('SOURCE_B', 'land', 'INPUT_PARAMS', '{"rows": 1}'),
    ('SOURCE_B', 'land', 'LINEAGE_SOURCE', 'client_beta.events'),
    ('SOURCE_B', 'setup_prs', 'SQL_ACTION', 'SETUP_TABLE'),
    ('SOURCE_B', 'setup_prs', 'SELECT_QUERY', 'SELECT b.support_identifier AS interaction_id, b.agent AS agent_code, b.regarding AS support_area, CAST(b.event_time AS DATE) AS contact_date, b.status, CAST(b.handle_time AS INTEGER) AS handle_seconds, CAST(b.score AS INTEGER) AS rating, CAST(0 AS BIGINT) AS parsed_by FROM lnd.client_beta b WHERE 1 = 0'),
    ('SOURCE_B', 'parse', 'SQL_ACTION', 'APPEND_TABLE'),
    ('SOURCE_B', 'parse', 'SCRIPT_FILE', 'sql_scripts/prs_beta.sql'),
    ('SOURCE_B', 'parse', 'PIPELINE_RUN_ID_SUBSTITUTION', 'true'),
    ('DEMO', 'land_agents', 'SCRIPT_KIND', 'INGESTION'),
    ('DEMO', 'land_agents', 'SCRIPT_FILE', 'python_scripts/agents.py'),
    ('DEMO', 'land_agents', 'LINEAGE_SOURCE', 'hr.agents'),
    ('DEMO', 'flaky_feed', 'SCRIPT_KIND', 'INGESTION'),
    ('DEMO', 'flaky_feed', 'SCRIPT_FILE', 'python_scripts/flaky.py'),
    ('DEMO', 'flaky_feed', 'DOCUMENTATION', 'A feed that is not ready the first time it is read.'),
    ('DEMO', 'on_failure', 'EMAIL_TO', 'support-oncall@example.com'),
    ('DEMO', 'on_failure', 'EMAIL_ON_STATUS', 'FAILED'),
    ('DEMO', 'on_failure', 'EMAIL_SUBJECT', '$$pipeline_code: a feed failed'),
    ('DEMO', 'on_failure', 'EMAIL_BODY', 'Run $$pipeline_run_id of $$pipeline_code failed: $$error_message'),
    ('DEMO', 'agents', 'SQL_ACTION', 'SCD1_MERGE'),
    ('DEMO', 'agents', 'SELECT_QUERY', 'SELECT agent_code, agent_name, team, email FROM lnd.agents WHERE left_company = ''N'''),
    ('DEMO', 'agents', 'MERGE_KEY', 'agent_code'),
    ('DEMO', 'agents', 'MERGE_COMPARE_COLUMNS', 'agent_name|team|email'),
    ('DEMO', 'agents', 'PRESERVE_TARGET', 'true'),
    ('DEMO', 'agents', 'DOCUMENTATION', 'Keeps one row per agent, up to date; an email the feed leaves out keeps the one on file.'),
    ('DEMO', 'retire_agents', 'SQL_ACTION', 'DELETE_ROWS'),
    ('DEMO', 'retire_agents', 'SELECT_QUERY', 'SELECT agent_code FROM lnd.agents WHERE left_company = ''Y'''),
    ('DEMO', 'retire_agents', 'MERGE_KEY', 'agent_code'),
    ('DEMO', 'setup_agent_history', 'SQL_ACTION', 'SETUP_TABLE'),
    ('DEMO', 'setup_agent_history', 'SELECT_QUERY', 'SELECT agent_code, team FROM lnd.agents'),
    ('DEMO', 'agent_history', 'SQL_ACTION', 'SCD2_MERGE'),
    ('DEMO', 'agent_history', 'SELECT_QUERY', 'SELECT agent_code, team FROM lnd.agents'),
    ('DEMO', 'agent_history', 'MERGE_KEY', 'agent_code'),
    ('DEMO', 'agent_history', 'MERGE_COMPARE_COLUMNS', 'team'),
    ('DEMO', 'agent_history', 'DOCUMENTATION', 'Keeps every team an agent has been in, and when.'),
    ('DEMO', 'interactions', 'SQL_ACTION', 'CREATE_TABLE'),
    ('DEMO', 'interactions', 'SCRIPT_FILE', 'sql_scripts/pre_dm_interactions.sql'),
    ('DEMO', 'setup_fact', 'SQL_ACTION', 'SETUP_TABLE'),
    ('DEMO', 'setup_fact', 'SCRIPT_FILE', 'sql_scripts/support_fact.sql'),
    ('DEMO', 'fact', 'SQL_ACTION', 'OVERWRITE_TABLE'),
    ('DEMO', 'fact', 'SCRIPT_FILE', 'sql_scripts/support_fact.sql'),
    ('DEMO', 'fact', 'DOCUMENTATION', 'One row per interaction, from every client, with the agent''s team and the support area''s name.'),
    ('DEMO', 'area_summary', 'SQL_ACTION', 'CREATE_VIEW'),
    ('DEMO', 'area_summary', 'SCRIPT_FILE', 'sql_scripts/area_summary.sql'),
    ('DEMO', 'source_counts', 'SQL_ACTION', 'CREATE_TABLE'),
    ('DEMO', 'source_counts', 'SELECT_QUERY', 'SELECT source_system, COUNT(*) AS interactions FROM pre_dm.interactions GROUP BY source_system'),
    ('DEMO', 'drop_source_counts', 'SQL_ACTION', 'DROP_TABLE'),
    ('DEMO', 'alert', 'EMAIL_TO', 'support-leads@example.com'),
    ('DEMO', 'alert', 'EMAIL_SUBJECT', '$$pipeline_code: $$status'),
    ('DEMO', 'alert', 'EMAIL_BODY', 'Run $$pipeline_run_id of $$pipeline_code ended $$status.'),
    ('DEMO', 'alert', 'EMAIL_PIPELINES', 'SOURCE_A|SOURCE_B|DEMO'),
    ('EXPORT', 'export', 'SCRIPT_KIND', 'UTILITY'),
    ('EXPORT', 'export', 'SCRIPT_FILE', 'python_scripts/wait.py'),
    ('EXPORT', 'export', 'INPUT_PARAMS', '{"seconds": 8}'),
    ('EXPORT', 'export', 'TASK_TIMEOUT_SECONDS', '2'),
    ('BACKFILL', 'prepare', 'SCRIPT_KIND', 'UTILITY'),
    ('BACKFILL', 'prepare', 'SCRIPT_FILE', 'python_scripts/wait.py'),
    ('BACKFILL', 'prepare', 'INPUT_PARAMS', '{"seconds": 0}'),
    ('BACKFILL', 'backfill', 'SCRIPT_KIND', 'UTILITY'),
    ('BACKFILL', 'backfill', 'SCRIPT_FILE', 'python_scripts/wait.py'),
    ('BACKFILL', 'backfill', 'INPUT_PARAMS', '{"seconds": 30}')
) v
JOIN CFG_PIPELINES p ON p.PIPELINE_CODE = v.column1
JOIN CFG_TASKS t ON t.PIPELINE_ID = p.PIPELINE_ID AND t.TASK_CODE = v.column2;

INSERT INTO CFG_TASK_DEPENDENCY (PIPELINE_ID, TASK_ID, DEPENDS_ON_PIPELINE_ID, DEPENDS_ON_TASK_ID,
                                 DEPENDENCY_TYPE)
SELECT t.PIPELINE_ID, t.TASK_ID, u.PIPELINE_ID, u.TASK_ID, v.column5
FROM (VALUES
    ('SOURCE_A', 'setup_prs', 'SOURCE_A', 'land', 'SUCCESS'),
    ('SOURCE_A', 'parse', 'SOURCE_A', 'setup_prs', 'SUCCESS'),
    ('SOURCE_A', 'parse', 'SOURCE_A', 'land', 'HAS_DATA'),
    ('SOURCE_A', 'purge_test_calls', 'SOURCE_A', 'parse', 'SUCCESS'),
    ('SOURCE_B', 'setup_prs', 'SOURCE_B', 'land', 'SUCCESS'),
    ('SOURCE_B', 'parse', 'SOURCE_B', 'setup_prs', 'SUCCESS'),
    ('DEMO', 'agents', 'DEMO', 'land_agents', 'SUCCESS'),
    ('DEMO', 'retire_agents', 'DEMO', 'agents', 'SUCCESS'),
    ('DEMO', 'setup_agent_history', 'DEMO', 'land_agents', 'SUCCESS'),
    ('DEMO', 'agent_history', 'DEMO', 'setup_agent_history', 'SUCCESS'),
    ('DEMO', 'on_failure', 'DEMO', 'flaky_feed', 'FAILURE'),
    ('DEMO', 'interactions', 'DEMO', 'flaky_feed', 'SUCCESS'),
    ('DEMO', 'interactions', 'SOURCE_A', 'purge_test_calls', 'SUCCESS'),
    ('DEMO', 'interactions', 'SOURCE_B', 'parse', 'SUCCESS'),
    ('DEMO', 'setup_fact', 'DEMO', 'interactions', 'HAS_DATA'),
    ('DEMO', 'setup_fact', 'DEMO', 'retire_agents', 'SUCCESS'),
    ('DEMO', 'fact', 'DEMO', 'setup_fact', 'SUCCESS'),
    ('DEMO', 'quality', 'DEMO', 'fact', 'SUCCESS'),
    ('DEMO', 'area_summary', 'DEMO', 'fact', 'SUCCESS'),
    ('DEMO', 'area_summary', 'DEMO', 'quality', 'SUCCESS'),
    ('DEMO', 'source_counts', 'DEMO', 'interactions', 'SUCCESS'),
    ('DEMO', 'source_counts', 'DEMO', 'setup_fact', 'SUCCESS'),
    ('DEMO', 'source_counts', 'DEMO', 'fact', 'SUCCESS'),
    ('DEMO', 'drop_source_counts', 'DEMO', 'source_counts', 'SUCCESS'),
    ('DEMO', 'alert', 'DEMO', 'drop_source_counts', 'ALWAYS'),
    ('DEMO', 'alert', 'DEMO', 'area_summary', 'ALWAYS'),
    ('DEMO', 'alert', 'DEMO', 'quality', 'ALWAYS'),
    ('DEMO', 'alert', 'DEMO', 'agent_history', 'ALWAYS'),
    ('BACKFILL', 'backfill', 'BACKFILL', 'prepare', 'SUCCESS')
) v
JOIN CFG_PIPELINES p ON p.PIPELINE_CODE = v.column1
JOIN CFG_TASKS t ON t.PIPELINE_ID = p.PIPELINE_ID AND t.TASK_CODE = v.column2
JOIN CFG_PIPELINES up ON up.PIPELINE_CODE = v.column3
JOIN CFG_TASKS u ON u.PIPELINE_ID = up.PIPELINE_ID AND u.TASK_CODE = v.column4;

-- DEMO builds on both clients' pipelines: a run starts only after each has succeeded again.
INSERT INTO CFG_PIPELINE_DEPENDENCY (PIPELINE_ID, DEPENDS_ON_PIPELINE_ID, DEPENDENCY_TYPE)
SELECT p.PIPELINE_ID, u.PIPELINE_ID, 'SUCCESS'
FROM CFG_PIPELINES p
JOIN CFG_PIPELINES u ON u.PIPELINE_CODE IN ('SOURCE_A', 'SOURCE_B')
WHERE p.PIPELINE_CODE = 'DEMO';


-- The support fact's checks: two in the first wave, one in the second.
INSERT INTO CFG_BUSINESS_RULES (BUSINESS_RULE_NAME, PIPELINE_ID, TASK_ID, BUSINESS_RULE_SQL,
                                BUSINESS_RULE_TYPE, BUSINESS_RULE_KEY_COLUMN, TARGET_TABLE_ID,
                                SEQUENCE_NUMBER)
SELECT v.column1, t.PIPELINE_ID, t.TASK_ID, v.column2, v.column3, 'fact_key',
       (SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='dm' AND TABLE_NAME='support_fact'),
       CAST(v.column4 AS INTEGER)
FROM (VALUES
    ('unknown agent',
     'SELECT t.fact_key FROM $$rows_in_scope t JOIN ds.support_areas s ON s.area_name = t.area_name AND t.team IS NULL',
     'INCOMPLETE', '1'),
    ('rating out of range',
     'SELECT t.fact_key FROM $$rows_in_scope t JOIN ds.support_areas s ON s.area_name = t.area_name AND (t.rating < 1 OR t.rating > 5)',
     'REJECT', '1'),
    ('long call',
     'SELECT t.fact_key FROM $$rows_in_scope t JOIN ds.support_areas s ON s.area_name = t.area_name AND t.handle_seconds > 600',
     'REPORT', '2')
) v
JOIN CFG_PIPELINES p ON p.PIPELINE_CODE = 'DEMO'
JOIN CFG_TASKS t ON t.PIPELINE_ID = p.PIPELINE_ID AND t.TASK_CODE = 'quality';

-- Table checks record one result rather than flagging individual fact rows.
INSERT INTO CFG_BUSINESS_RULES (BUSINESS_RULE_NAME,PIPELINE_ID,TASK_ID,BUSINESS_RULE_SQL,
 BUSINESS_RULE_TYPE,BUSINESS_RULE_KEY_COLUMN,TARGET_TABLE_ID,SEQUENCE_NUMBER,BUSINESS_RULE_LEVEL)
SELECT v.column1,t.PIPELINE_ID,t.TASK_ID,v.column2,v.column3,NULL,
 (SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='dm' AND TABLE_NAME='support_fact'),3,'TABLE'
FROM (VALUES
 ('fact has rows','SELECT CASE WHEN COUNT(*)>0 THEN ''Y'' ELSE ''N'' END AS PASSED, CAST(COUNT(*) AS VARCHAR) AS OBSERVED FROM dm.support_fact','REJECT'),
 ('missing teams','SELECT CASE WHEN SUM(CASE WHEN team IS NULL THEN 1 ELSE 0 END)*100.0<COUNT(*)*5 THEN ''Y'' ELSE ''N'' END AS PASSED, CAST(SUM(CASE WHEN team IS NULL THEN 1 ELSE 0 END) AS VARCHAR) AS OBSERVED, ''NULL teams; limit is under 5 percent'' AS DETAIL FROM $$rows_in_scope','REPORT')
) v JOIN CFG_PIPELINES p ON p.PIPELINE_CODE='DEMO'
JOIN CFG_TASKS t ON t.PIPELINE_ID=p.PIPELINE_ID AND t.TASK_CODE='quality';

-- Source shapes the Python scripts land, available before the first run.

INSERT INTO CFG_COLUMNS (TABLE_ID, COLUMN_NAME, DATA_TYPE, COLUMN_POSITION) VALUES
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'interaction_id', 'BIGINT', 1),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'agent_code', 'VARCHAR(100)', 2),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'support_area', 'VARCHAR(100)', 3),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'contact_date', 'VARCHAR(100)', 4),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'status', 'VARCHAR(100)', 5),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'duration_seconds', 'VARCHAR(100)', 6),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'rating', 'VARCHAR(100)', 7),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'pipeline_run_id', 'BIGINT', 8),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'pipeline_id', 'BIGINT', 9),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_alpha'), 'task_run_id', 'BIGINT', 10),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'support_identifier', 'BIGINT', 1),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'agent', 'VARCHAR(100)', 2),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'regarding', 'VARCHAR(100)', 3),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'event_time', 'TIMESTAMP', 4),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'status', 'VARCHAR(100)', 5),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'handle_time', 'BIGINT', 6),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'score', 'BIGINT', 7),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'pipeline_run_id', 'BIGINT', 8),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'pipeline_id', 'BIGINT', 9),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='client_beta'), 'task_run_id', 'BIGINT', 10),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='agents'), 'agent_code', 'VARCHAR(100)', 1),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='agents'), 'agent_name', 'VARCHAR(100)', 2),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='agents'), 'team', 'VARCHAR(100)', 3),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='agents'), 'email', 'VARCHAR(100)', 4),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='agents'), 'left_company', 'VARCHAR(100)', 5),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='agents'), 'pipeline_run_id', 'BIGINT', 6),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='agents'), 'pipeline_id', 'BIGINT', 7),
    ((SELECT TABLE_ID FROM CFG_TABLES WHERE SCHEMA_NAME='lnd' AND TABLE_NAME='agents'), 'task_run_id', 'BIGINT', 8);
