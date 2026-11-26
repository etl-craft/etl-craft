-- A step added between two others, and parameters added to and retired from existing tasks.
-- validate_feed now runs between fetch_orders and load_orders in SALES_DAILY: the new task, its
-- parameters, its dependencies, and the dependency it replaces retired.

CREATE TEMPORARY TABLE codes_in_use (CODE VARCHAR(300) NOT NULL, ID BIGINT NOT NULL);

INSERT INTO codes_in_use (CODE, ID)
SELECT v.column1 || '.' || v.column2, t.TASK_ID
FROM (VALUES
    ('SALES_DAILY', 'fetch_orders'),
    ('SALES_DAILY', 'load_orders')
) v
LEFT JOIN CFG_PIPELINES p ON p.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND p.PIPELINE_CODE = v.column1 AND p.ACTIVE_FLAG = 'Y'
LEFT JOIN CFG_TASKS t ON t.PIPELINE_ID = p.PIPELINE_ID AND t.TASK_CODE = v.column2
                     AND t.ACTIVE_FLAG = 'Y';

INSERT INTO CFG_TASKS (PIPELINE_ID, TASK_CODE, TASK_TYPE, HANDLER)
SELECT p.PIPELINE_ID, v.column2, v.column3, v.column4
FROM (VALUES
    ('SALES_DAILY', 'validate_feed', 'ETL', 'PYTHON')
) v
LEFT JOIN CFG_PIPELINES p ON p.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND p.PIPELINE_CODE = v.column1 AND p.ACTIVE_FLAG = 'Y';

-- The new task's parameters, and a parameter added to an existing task.
INSERT INTO CFG_TASK_PARAMETERS (TASK_ID, PARAMETER_NAME, PARAMETER_VALUE)
SELECT t.TASK_ID, v.column3, v.column4
FROM (VALUES
    ('SALES_DAILY', 'validate_feed', 'SCRIPT_KIND', 'INGESTION'),
    ('SALES_DAILY', 'validate_feed', 'SCRIPT_FILE', 'python_scripts/sales/validate_feed.py'),
    ('SALES_DAILY', 'validate_feed', 'INPUT_PARAMS', '{"table": "lnd.orders_uk", "min_rows": 1}'),
    ('SALES_DAILY', 'load_orders', 'RETRIES', '1')
) v
LEFT JOIN CFG_PIPELINES p ON p.PROJECT_ID = (SELECT PROJECT_ID FROM ETL_CRAFT_PROJECT)
    AND p.PIPELINE_CODE = v.column1 AND p.ACTIVE_FLAG = 'Y'
LEFT JOIN CFG_TASKS t ON t.PIPELINE_ID = p.PIPELINE_ID AND t.TASK_CODE = v.column2
                     AND t.ACTIVE_FLAG = 'Y';

UPDATE CFG_TASKS SET RUN_CONDITION = 'fetch_orders.SUCCESS'
WHERE TASK_CODE = 'validate_feed' AND PIPELINE_ID = (
    SELECT PIPELINE_ID FROM CFG_TASKS WHERE TASK_ID =
        (SELECT ID FROM codes_in_use WHERE CODE = 'SALES_DAILY.load_orders')
);

UPDATE CFG_TASKS SET RUN_CONDITION = 'validate_feed.SUCCESS AND setup_orders.SUCCESS'
WHERE TASK_ID = (SELECT ID FROM codes_in_use WHERE CODE = 'SALES_DAILY.load_orders');

-- A parameter retired: fetch_orders goes back to the default retry delay.
UPDATE CFG_TASK_PARAMETERS
SET ACTIVE_FLAG = 'N'
WHERE PARAMETER_NAME = 'RETRY_DELAY_SECONDS' AND ACTIVE_FLAG = 'Y'
  AND TASK_ID = (SELECT ID FROM codes_in_use WHERE CODE = 'SALES_DAILY.fetch_orders');

DROP TABLE codes_in_use;
