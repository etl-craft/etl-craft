-- A run can be a one-time full refresh: the tasks in its plan read from the start, and the append
-- targets the operator confirmed are emptied before their load. FULL_REFRESH_PLAN holds that plan.
ALTER TABLE AUD_PIPELINES_RUN_LOG ADD COLUMN FULL_REFRESH VARCHAR(1) NOT NULL DEFAULT 'N' CONSTRAINT ck_run_full_refresh CHECK (FULL_REFRESH IN ('Y','N'));
ALTER TABLE AUD_PIPELINES_RUN_LOG ADD COLUMN FULL_REFRESH_PLAN TEXT CONSTRAINT ck_run_full_refresh_plan CHECK ((FULL_REFRESH = 'Y') = (FULL_REFRESH_PLAN IS NOT NULL));
