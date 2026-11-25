-- create_table
CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount;

SELECT COUNT(*) FROM lake.sales.etl_stage_7_golden_1;

CREATE TABLE lake.sales.etl_replace_ids_7_golden_2 AS SELECT s.*, CAST(42 AS BIGINT) AS PIPELINE_RUN_ID, CAST(1 AS BIGINT) AS PIPELINE_ID, CAST(7 AS BIGINT) AS TASK_RUN_ID FROM lake.sales.etl_stage_7_golden_1 s;

SELECT COUNT(*) FROM lake.sales.etl_replace_ids_7_golden_2;

CREATE OR REPLACE TABLE lake.sales.orders AS SELECT s.*, 0 + CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT) AS ROW_ID FROM lake.sales.etl_replace_ids_7_golden_2 s;

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;

DROP TABLE IF EXISTS lake.sales.etl_replace_ids_7_golden_2;

DROP TABLE IF EXISTS lake.sales.etl_replace_ids_7_golden_2;

-- create_table_replace
CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount;

SELECT COUNT(*) FROM lake.sales.etl_stage_7_golden_1;

CREATE TABLE lake.sales.etl_replace_ids_7_golden_2 AS SELECT s.*, CAST(42 AS BIGINT) AS PIPELINE_RUN_ID, CAST(1 AS BIGINT) AS PIPELINE_ID, CAST(7 AS BIGINT) AS TASK_RUN_ID FROM lake.sales.etl_stage_7_golden_1 s;

SELECT COUNT(*) FROM lake.sales.etl_replace_ids_7_golden_2;

SELECT COALESCE(MAX(ROW_ID), 0) FROM lake.sales.orders;

SHOW CREATE TABLE lake.sales.orders;

CREATE OR REPLACE TABLE lake.sales.orders AS SELECT s.*, 1 + CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT) AS ROW_ID FROM lake.sales.etl_replace_ids_7_golden_2 AS s;

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;

DROP TABLE IF EXISTS lake.sales.etl_replace_ids_7_golden_2;

DROP TABLE IF EXISTS lake.sales.etl_replace_ids_7_golden_2;

-- overwrite_table
CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount;

SELECT COUNT(*) FROM lake.sales.etl_stage_7_golden_1;

SELECT COALESCE(MAX(ROW_ID), 0) FROM lake.sales.orders;

SHOW CREATE TABLE lake.sales.orders;

CREATE OR REPLACE TABLE lake.sales.orders AS SELECT CAST(id AS BIGINT) AS id, CAST(name AS VARCHAR) AS name, CAST(amount AS DECIMAL) AS amount, CAST(:pipeline_run_id AS BIGINT) AS PIPELINE_RUN_ID, CAST(:pipeline_id AS BIGINT) AS PIPELINE_ID, CAST(:task_run_id AS BIGINT) AS TASK_RUN_ID, CAST(:now AS TIMESTAMP(6) WITH TIME ZONE) AS UPDATE_DATE, 1 + CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT) AS ROW_ID FROM lake.sales.etl_stage_7_golden_1;

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;

-- append_table
CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount;

SELECT COUNT(*) FROM lake.sales.etl_stage_7_golden_1;

SELECT COALESCE(MAX(ROW_ID), 0) FROM lake.sales.orders;

DELETE FROM lake.sales.orders WHERE TASK_RUN_ID = :task_run_id;

INSERT INTO lake.sales.orders (id, name, amount, PIPELINE_RUN_ID, CREATE_DATE, TASK_RUN_ID, PIPELINE_ID, ROW_ID) SELECT id, name, amount, :pipeline_run_id, :now, :task_run_id, :pipeline_id, 1 + CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT) FROM lake.sales.etl_stage_7_golden_1;

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;

SELECT COUNT(*) FROM lake.sales.orders;

-- scd1_merge
SELECT ETL_PROTECTION AS protection FROM lake.sales.orders WHERE ETL_PROTECTION IS NOT NULL AND ETL_PROTECTION NOT LIKE :baseline LIMIT 1;

CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT etl_src.*, lower(to_hex(md5(to_utf8(CASE WHEN etl_src.name IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(etl_src.name AS VARCHAR)) AS VARCHAR) || ':' || CAST(etl_src.name AS VARCHAR) END || CASE WHEN etl_src.amount IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(CAST(etl_src.amount AS DECIMAL(10,2)) AS VARCHAR)) AS VARCHAR) || ':' || CAST(CAST(etl_src.amount AS DECIMAL(10,2)) AS VARCHAR) END)))) AS HASH_KEY FROM (
SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount
) etl_src;

SELECT COALESCE(SUM(n), 0) AS source_rows, COALESCE(SUM(n - 1), 0) AS duplicate_rows, COALESCE(SUM(CASE WHEN k0 IS NULL THEN n ELSE 0 END), 0) AS null_keys, COALESCE(SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END), 0) AS duplicate_keys , (SELECT COUNT(*) FROM lake.sales.etl_stage_7_golden_1 s WHERE NOT EXISTS (SELECT 1 FROM lake.sales.orders t WHERE t.id=s.id)) AS new_keys FROM (SELECT id AS k0, COUNT(*) AS n FROM lake.sales.etl_stage_7_golden_1 GROUP BY id) counted;

CREATE TABLE lake.sales.etl_scd1_ids_7_golden_2 AS SELECT s.*, NOT EXISTS (SELECT 1 FROM lake.sales.orders t WHERE t.id = s.id) AS __etl_insert_key FROM lake.sales.etl_stage_7_golden_1 s;

SELECT COUNT(*) FROM lake.sales.etl_scd1_ids_7_golden_2 WHERE __etl_insert_key;

SELECT COALESCE(MAX(ROW_ID), 0) FROM lake.sales.orders;

MERGE INTO lake.sales.orders t USING (SELECT s.*, CASE WHEN __etl_insert_key THEN 1 + CAST(ROW_NUMBER() OVER (PARTITION BY __etl_insert_key ORDER BY NULL) AS BIGINT) END AS ROW_ID FROM lake.sales.etl_scd1_ids_7_golden_2 s) s ON t.id = s.id WHEN MATCHED AND ((t.HASH_KEY IS DISTINCT FROM s.HASH_KEY OR t.DELETE_FLAG = 'Y')) THEN UPDATE SET name = s.name, amount = s.amount, HASH_KEY = s.HASH_KEY, PIPELINE_RUN_ID = :pipeline_run_id, TASK_RUN_ID = :task_run_id, PIPELINE_ID = :pipeline_id, UPDATE_DATE = :now, UPDATED_BY = :updated_by, DELETE_FLAG = 'N', ACTIVE_FLAG = 'Y', ETL_PROTECTION = :protection_baseline, ETL_ROW_FINGERPRINT = lower(to_hex(md5(to_utf8(CASE WHEN s.id IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(s.id AS VARCHAR)) AS VARCHAR) || ':' || CAST(s.id AS VARCHAR) END || CASE WHEN s.name IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(s.name AS VARCHAR)) AS VARCHAR) || ':' || CAST(s.name AS VARCHAR) END || CASE WHEN s.amount IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(CAST(s.amount AS DECIMAL(10,2)) AS VARCHAR)) AS VARCHAR) || ':' || CAST(CAST(s.amount AS DECIMAL(10,2)) AS VARCHAR) END || CASE WHEN CAST(:protection_baseline AS VARCHAR) IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(CAST(:protection_baseline AS VARCHAR) AS VARCHAR)) AS VARCHAR) || ':' || CAST(CAST(:protection_baseline AS VARCHAR) AS VARCHAR) END)))), ETL_PROTECTION_REQUEST_ID = NULL WHEN NOT MATCHED THEN INSERT (id, name, amount, HASH_KEY, PIPELINE_RUN_ID, PIPELINE_ID, TASK_RUN_ID, CREATE_DATE, CREATED_BY, UPDATE_DATE, UPDATED_BY, DELETE_FLAG, ACTIVE_FLAG, ROW_ID, ETL_PROTECTION, ETL_ROW_FINGERPRINT, ETL_PROTECTION_REQUEST_ID) VALUES (s.id, s.name, s.amount, s.HASH_KEY, :pipeline_run_id, :pipeline_id, :task_run_id, :now, :updated_by, :now, :updated_by, 'N', 'Y', s.ROW_ID, :protection_baseline, lower(to_hex(md5(to_utf8(CASE WHEN s.id IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(s.id AS VARCHAR)) AS VARCHAR) || ':' || CAST(s.id AS VARCHAR) END || CASE WHEN s.name IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(s.name AS VARCHAR)) AS VARCHAR) || ':' || CAST(s.name AS VARCHAR) END || CASE WHEN s.amount IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(CAST(s.amount AS DECIMAL(10,2)) AS VARCHAR)) AS VARCHAR) || ':' || CAST(CAST(s.amount AS DECIMAL(10,2)) AS VARCHAR) END || CASE WHEN CAST(:protection_baseline AS VARCHAR) IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(CAST(:protection_baseline AS VARCHAR) AS VARCHAR)) AS VARCHAR) || ':' || CAST(CAST(:protection_baseline AS VARCHAR) AS VARCHAR) END)))), NULL);

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;

SELECT COUNT(*) FROM lake.sales.orders;

DROP TABLE IF EXISTS lake.sales.etl_scd1_ids_7_golden_2;

DROP TABLE IF EXISTS lake.sales.etl_scd1_ids_7_golden_2;

-- scd2_merge
SELECT ETL_PROTECTION AS protection FROM lake.sales.orders WHERE ETL_PROTECTION IS NOT NULL AND ETL_PROTECTION NOT LIKE :baseline LIMIT 1;

CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT etl_src.*, lower(to_hex(md5(to_utf8(CASE WHEN etl_src.name IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(etl_src.name AS VARCHAR)) AS VARCHAR) || ':' || CAST(etl_src.name AS VARCHAR) END || CASE WHEN etl_src.amount IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(CAST(etl_src.amount AS DECIMAL(10,2)) AS VARCHAR)) AS VARCHAR) || ':' || CAST(CAST(etl_src.amount AS DECIMAL(10,2)) AS VARCHAR) END)))) AS HASH_KEY FROM (
SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount
) etl_src;

SELECT COALESCE(SUM(n), 0) AS source_rows, COALESCE(SUM(n - 1), 0) AS duplicate_rows, COALESCE(SUM(CASE WHEN k0 IS NULL THEN n ELSE 0 END), 0) AS null_keys, COALESCE(SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END), 0) AS duplicate_keys  FROM (SELECT id AS k0, COUNT(*) AS n FROM lake.sales.etl_stage_7_golden_1 GROUP BY id) counted;

CREATE TABLE lake.sales.etl_scd2_ids_7_golden_2 AS SELECT * FROM (SELECT s.*, t.ROW_ID AS __etl_match_row_id, FALSE AS __etl_insert_version FROM lake.sales.etl_stage_7_golden_1 s JOIN lake.sales.orders t ON t.id=s.id AND t.ACTIVE_FLAG='Y' WHERE t.HASH_KEY IS DISTINCT FROM s.HASH_KEY OR t.DELETE_FLAG = 'Y' UNION ALL SELECT s.*, CAST(NULL AS BIGINT) AS __etl_match_row_id, TRUE AS __etl_insert_version FROM lake.sales.etl_stage_7_golden_1 s LEFT JOIN lake.sales.orders t ON t.id=s.id AND t.ACTIVE_FLAG='Y' AND NOT (t.HASH_KEY IS DISTINCT FROM s.HASH_KEY OR t.DELETE_FLAG = 'Y') WHERE t.ROW_ID IS NULL) changes;

SELECT COALESCE(SUM(CASE WHEN __etl_insert_version THEN 0 ELSE 1 END),0) AS closed, COALESCE(SUM(CASE WHEN __etl_insert_version THEN 1 ELSE 0 END),0) AS inserted FROM lake.sales.etl_scd2_ids_7_golden_2 changes;

SELECT COALESCE(MAX(ROW_ID), 0) FROM lake.sales.orders;

MERGE INTO lake.sales.orders t USING (SELECT numbered.*, CASE WHEN __etl_insert_version THEN 1 + CAST(ROW_NUMBER() OVER (PARTITION BY __etl_insert_version ORDER BY NULL) AS BIGINT) ELSE __etl_match_row_id END AS __etl_new_row_id FROM lake.sales.etl_scd2_ids_7_golden_2 numbered) s ON t.ROW_ID=s.__etl_match_row_id WHEN MATCHED THEN UPDATE SET ACTIVE_FLAG='N', UPDATE_DATE=:now, UPDATED_BY=:updated_by, PIPELINE_RUN_ID=:pipeline_run_id, TASK_RUN_ID=:task_run_id, PIPELINE_ID=:pipeline_id, ETL_PROTECTION_REQUEST_ID=:protection_request_id WHEN NOT MATCHED AND s.__etl_insert_version THEN INSERT (id, name, amount, HASH_KEY, PIPELINE_RUN_ID, PIPELINE_ID, TASK_RUN_ID, CREATE_DATE, CREATED_BY, UPDATE_DATE, UPDATED_BY, DELETE_FLAG, ACTIVE_FLAG, ROW_ID, ETL_PROTECTION, ETL_ROW_FINGERPRINT, ETL_PROTECTION_REQUEST_ID) VALUES (s.id, s.name, s.amount, s.HASH_KEY, :pipeline_run_id, :pipeline_id, :task_run_id, :now, :updated_by, :now, :updated_by, 'N', 'Y', s.__etl_new_row_id, :protection_baseline, lower(to_hex(md5(to_utf8(CASE WHEN s.id IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(s.id AS VARCHAR)) AS VARCHAR) || ':' || CAST(s.id AS VARCHAR) END || CASE WHEN s.name IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(s.name AS VARCHAR)) AS VARCHAR) || ':' || CAST(s.name AS VARCHAR) END || CASE WHEN s.amount IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(CAST(s.amount AS DECIMAL(10,2)) AS VARCHAR)) AS VARCHAR) || ':' || CAST(CAST(s.amount AS DECIMAL(10,2)) AS VARCHAR) END || CASE WHEN CAST(:protection_baseline AS VARCHAR) IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(CAST(:protection_baseline AS VARCHAR) AS VARCHAR)) AS VARCHAR) || ':' || CAST(CAST(:protection_baseline AS VARCHAR) AS VARCHAR) END)))), NULL);

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;

SELECT COUNT(*) FROM lake.sales.orders;

DROP TABLE IF EXISTS lake.sales.etl_scd2_ids_7_golden_2;

DROP TABLE IF EXISTS lake.sales.etl_scd2_ids_7_golden_2;

-- delete_rows
SELECT ETL_PROTECTION AS protection FROM lake.sales.orders WHERE ETL_PROTECTION IS NOT NULL AND ETL_PROTECTION NOT LIKE :baseline LIMIT 1;

CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT 1 AS id;

SELECT COALESCE(SUM(n), 0) AS source_rows, COALESCE(SUM(n - 1), 0) AS duplicate_rows, COALESCE(SUM(CASE WHEN k0 IS NULL THEN n ELSE 0 END), 0) AS null_keys, COALESCE(SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END), 0) AS duplicate_keys  FROM (SELECT id AS k0, COUNT(*) AS n FROM lake.sales.etl_stage_7_golden_1 GROUP BY id) counted;

MERGE INTO lake.sales.orders t USING (SELECT id FROM lake.sales.etl_stage_7_golden_1 GROUP BY id) s ON t.id=s.id WHEN MATCHED AND (t.ACTIVE_FLAG='Y' AND t.DELETE_FLAG='N') THEN UPDATE SET DELETE_FLAG='Y', ACTIVE_FLAG='N', UPDATE_DATE=:now, PIPELINE_RUN_ID=:pipeline_run_id, PIPELINE_ID=:pipeline_id, TASK_RUN_ID=:task_run_id, UPDATED_BY=:updated_by;

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;

-- delete_rows_hard
SELECT ETL_PROTECTION AS protection FROM lake.sales.orders WHERE ETL_PROTECTION IS NOT NULL AND ETL_PROTECTION NOT LIKE :baseline LIMIT 1;

CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT 1 AS id;

SELECT COALESCE(SUM(n), 0) AS source_rows, COALESCE(SUM(n - 1), 0) AS duplicate_rows, COALESCE(SUM(CASE WHEN k0 IS NULL THEN n ELSE 0 END), 0) AS null_keys, COALESCE(SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END), 0) AS duplicate_keys  FROM (SELECT id AS k0, COUNT(*) AS n FROM lake.sales.etl_stage_7_golden_1 GROUP BY id) counted;

SELECT COALESCE(MAX(ROW_ID), 0) FROM lake.sales.orders;

SELECT DISTINCT lower(to_hex(md5(to_utf8(CASE WHEN t.id IS NULL THEN 'N' ELSE 'V' || CAST(LENGTH(CAST(t.id AS VARCHAR)) AS VARCHAR) || ':' || CAST(t.id AS VARCHAR) END)))) AS key_hash FROM lake.sales.orders t WHERE EXISTS (SELECT 1 FROM lake.sales.etl_stage_7_golden_1 s WHERE t.id=s.id) AND t.ETL_PROTECTION IS NOT NULL;

MERGE INTO lake.sales.orders t USING (SELECT DISTINCT id FROM lake.sales.etl_stage_7_golden_1) s ON t.id=s.id WHEN MATCHED THEN DELETE;

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;

-- drop_table
SELECT COALESCE(MAX(ROW_ID), 0) FROM lake.sales.orders;

DROP TABLE lake.sales.orders;

-- create_view
CREATE OR REPLACE VIEW lake.sales.orders AS SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount;

-- setup_table
CREATE TABLE lake.sales.etl_stage_7_golden_1 AS SELECT * FROM (
SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount
) etl_src WHERE 1 = 0;

CREATE TABLE lake.sales.orders AS SELECT s.id, s.name, s.amount, CAST(NULL AS BIGINT) AS PIPELINE_RUN_ID, CAST(NULL AS BIGINT) AS PIPELINE_ID, CAST(NULL AS BIGINT) AS TASK_RUN_ID, CAST(NULL AS VARCHAR(32)) AS HASH_KEY, CAST(NULL AS TIMESTAMP(6) WITH TIME ZONE) AS CREATE_DATE, CAST(NULL AS VARCHAR(255)) AS CREATED_BY, CAST(NULL AS TIMESTAMP(6) WITH TIME ZONE) AS UPDATE_DATE, CAST(NULL AS VARCHAR(255)) AS UPDATED_BY, CAST(NULL AS VARCHAR(1)) AS DELETE_FLAG, CAST(NULL AS VARCHAR(1)) AS ACTIVE_FLAG, CAST(NULL AS VARCHAR) AS ETL_PROTECTION, CAST(NULL AS VARCHAR(32)) AS ETL_ROW_FINGERPRINT, CAST(NULL AS VARCHAR(36)) AS ETL_PROTECTION_REQUEST_ID, CAST(NULL AS BIGINT) AS ROW_ID FROM lake.sales.etl_stage_7_golden_1 s WHERE 1 = 0;

DROP TABLE IF EXISTS lake.sales.etl_stage_7_golden_1;
