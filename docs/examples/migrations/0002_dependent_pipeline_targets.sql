CREATE TEMP TABLE task_targets (PIPELINE_CODE VARCHAR NOT NULL,TASK_CODE VARCHAR NOT NULL,
    SCHEMA_NAME VARCHAR NOT NULL,TABLE_NAME VARCHAR NOT NULL);
INSERT INTO task_targets (PIPELINE_CODE,TASK_CODE,SCHEMA_NAME,TABLE_NAME) VALUES
    ('SALES_MART','daily_totals','mart','daily_totals'),
    ('SALES_MART','region_totals','mart','region_totals'),
    ('SALES_MART','customer_totals','mart','customer_totals');
INSERT INTO CFG_TABLES (PROJECT_ID,SCHEMA_NAME,TABLE_NAME)
SELECT DISTINCT (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT),v.SCHEMA_NAME,v.TABLE_NAME FROM task_targets v
WHERE NOT EXISTS (SELECT 1 FROM CFG_TABLES o WHERE o.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND o.CATALOG_NAME IS NULL
    AND o.SCHEMA_NAME=v.SCHEMA_NAME AND o.TABLE_NAME=v.TABLE_NAME);

-- A pipeline that waits on another. SALES_MART starts once SALES_DAILY has succeeded, and one of
-- its tasks also waits on a task in SALES_DAILY: it runs only when that load wrote rows.

INSERT INTO CFG_PIPELINES (PROJECT_ID, PIPELINE_CODE, PIPELINE_NAME, DESCRIPTION, REFRESH_TYPE, RUN_SCHEDULE,
                           SCHEDULE_TIMEZONE)
VALUES
    ((SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT), 'SALES_MART', 'Sales mart', 'Daily, regional and customer totals of the checked orders.',
     'FULL', '30 6 * * *', 'Europe/London');

-- Pipeline dependencies: the pipeline, the pipeline it waits on, DEPENDENCY_TYPE, and
-- CONSUME_REPAIRS: 'Y' (the default) takes a repaired upstream run as new output, 'N' only a new
-- upstream run.
INSERT INTO CFG_PIPELINE_DEPENDENCY (PIPELINE_ID, DEPENDS_ON_PIPELINE_ID, DEPENDENCY_TYPE,
                                     CONSUME_REPAIRS)
SELECT p.PIPELINE_ID, u.PIPELINE_ID, v.column3, v.column4
FROM (VALUES
    ('SALES_MART', 'SALES_DAILY', 'SUCCESS', 'Y')
) v
LEFT JOIN CFG_PIPELINES p ON p.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND p.PIPELINE_CODE = v.column1 AND p.ACTIVE_FLAG = 'Y'
LEFT JOIN CFG_PIPELINES u ON u.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND u.PIPELINE_CODE = v.column2 AND u.ACTIVE_FLAG = 'Y';

-- publish runs once 2 of the 3 totals are built.
INSERT INTO CFG_TASKS (PIPELINE_ID, TASK_CODE, TASK_TYPE, HANDLER, RUN_CONDITION)
SELECT p.PIPELINE_ID, v.column2, v.column3, v.column4, v.column5
FROM (VALUES
    ('SALES_MART', 'daily_totals', 'ETL', 'SQL', NULL),
    ('SALES_MART', 'region_totals', 'ETL', 'SQL', NULL),
    ('SALES_MART', 'customer_totals', 'ETL', 'SQL', 'SALES_DAILY.load_orders.HAS_DATA'),
    ('SALES_MART', 'publish', 'ETL', 'PYTHON', 'AT_LEAST(2, daily_totals.SUCCESS, region_totals.SUCCESS, customer_totals.SUCCESS)'),
    ('SALES_MART', 'alert', 'ETL', 'ALERT', NULL)
) v
LEFT JOIN CFG_PIPELINES p ON p.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND p.PIPELINE_CODE = v.column1 AND p.ACTIVE_FLAG = 'Y';

-- An inline SELECT goes in SELECT_QUERY, its quotes doubled like any other text.
CREATE TEMP TABLE target_bindings (TASK_ID BIGINT NOT NULL,TABLE_ID BIGINT NOT NULL);
INSERT INTO target_bindings (TASK_ID,TABLE_ID)
SELECT t.TASK_ID,o.TABLE_ID FROM task_targets v
LEFT JOIN CFG_PIPELINES p ON p.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND p.PIPELINE_CODE=v.PIPELINE_CODE AND p.ACTIVE_FLAG='Y'
LEFT JOIN CFG_TASKS t ON t.PIPELINE_ID=p.PIPELINE_ID AND t.TASK_CODE=v.TASK_CODE AND t.ACTIVE_FLAG='Y'
LEFT JOIN CFG_TABLES o ON o.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND o.CATALOG_NAME IS NULL AND o.SCHEMA_NAME=v.SCHEMA_NAME
    AND o.TABLE_NAME=v.TABLE_NAME;
UPDATE CFG_TASKS SET TARGET_TABLE_ID=(SELECT b.TABLE_ID FROM target_bindings b WHERE b.TASK_ID=CFG_TASKS.TASK_ID)
WHERE TASK_ID IN (SELECT TASK_ID FROM target_bindings);
DROP TABLE target_bindings;
DROP TABLE task_targets;

INSERT INTO CFG_TASK_PARAMETERS (TASK_ID, PARAMETER_NAME, PARAMETER_VALUE)
SELECT t.TASK_ID, v.column3, v.column4
FROM (VALUES
    ('SALES_MART', 'daily_totals', 'SQL_ACTION', 'CREATE_TABLE'),
    ('SALES_MART', 'daily_totals', 'SELECT_QUERY',
     'SELECT CAST(ordered_at AS DATE) AS order_date, SUM(amount) AS total_amount FROM sales.orders_uk GROUP BY CAST(ordered_at AS DATE)'),
    ('SALES_MART', 'region_totals', 'SQL_ACTION', 'CREATE_TABLE'),
    ('SALES_MART', 'region_totals', 'SELECT_QUERY',
     'SELECT ''uk'' AS region, SUM(amount) AS total_amount FROM sales.orders_uk'),
    ('SALES_MART', 'customer_totals', 'SQL_ACTION', 'CREATE_TABLE'),
    ('SALES_MART', 'customer_totals', 'SELECT_QUERY',
     'SELECT customer_id, SUM(amount) AS total_amount FROM sales.orders_uk GROUP BY customer_id'),
    ('SALES_MART', 'publish', 'SCRIPT_KIND', 'UTILITY'),
    ('SALES_MART', 'publish', 'SCRIPT_FILE', 'python_scripts/sales/publish.py'),
    ('SALES_MART', 'alert', 'ALERT_CHANNEL', 'sales_data'),
    ('SALES_MART', 'alert', 'ALERT_ON', 'SUCCESS|COMPLETED_WITH_ERRORS|FAILURE'),
    ('SALES_MART', 'alert', 'ALERT_SUBJECT', '$$pipeline_code: $$trigger'),
    ('SALES_MART', 'alert', 'ALERT_BODY', 'Run $$pipeline_run_id ended $$status.')
) v
LEFT JOIN CFG_PIPELINES p ON p.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND p.PIPELINE_CODE = v.column1 AND p.ACTIVE_FLAG = 'Y'
LEFT JOIN CFG_TASKS t ON t.PIPELINE_ID = p.PIPELINE_ID AND t.TASK_CODE = v.column2
                     AND t.ACTIVE_FLAG = 'Y';
