-- A restart is a trigger kind of its own: widen ck_pipeline_run_trigger_kind to admit RESTART.
ALTER TABLE AUD_PIPELINES_RUN_LOG DROP CONSTRAINT ck_pipeline_run_trigger_kind;
ALTER TABLE AUD_PIPELINES_RUN_LOG ADD CONSTRAINT ck_pipeline_run_trigger_kind
    CHECK (TRIGGER_KIND IN ('SCHEDULE','MANUAL','BACKFILL','ORCHESTRATOR','STAND_IN','PIPELINE_TASK','RESTART'));
