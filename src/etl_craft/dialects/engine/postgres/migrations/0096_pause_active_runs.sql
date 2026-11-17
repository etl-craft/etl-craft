-- Existing pipeline pauses retain FINISH, the dispatch behaviour under which they were created.
DO $$
DECLARE holds_count bigint; wait_pauses_count bigint;
BEGIN
    SELECT count(*) INTO holds_count FROM AUD_CONTROL_REQUESTS WHERE ACTION IN ('HOLD','RELEASE');
    SELECT count(*) INTO wait_pauses_count FROM AUD_PIPELINE_PAUSES WHERE TASK_ID IS NOT NULL AND OUTCOME IS NULL;
    IF holds_count > 0 OR wait_pauses_count > 0 THEN
        RAISE EXCEPTION USING MESSAGE = 'this Engine DB contains holds or wait pauses from an unreleased development build; recreate this development Engine DB (HOLD/RELEASE controls=' || holds_count || ', wait pauses=' || wait_pauses_count || ')';
    END IF;
END $$;
ALTER TABLE AUD_CONTROL_REQUESTS DROP CONSTRAINT ck_control_action;
ALTER TABLE AUD_CONTROL_REQUESTS ADD CONSTRAINT ck_control_action CHECK (ACTION IN ('STOP','ABORT','RECOVER','RESTART','RUN_PAUSED'));
ALTER TABLE AUD_PIPELINE_PAUSES ADD COLUMN ACTIVE_RUNS VARCHAR(8);
UPDATE AUD_PIPELINE_PAUSES SET ACTIVE_RUNS='FINISH' WHERE TASK_ID IS NULL;
ALTER TABLE AUD_PIPELINE_PAUSES ADD CONSTRAINT ck_pause_scope CHECK (
    (TASK_ID IS NULL AND OUTCOME IS NULL AND ACTIVE_RUNS IS NOT NULL AND ACTIVE_RUNS IN ('DRAIN','FINISH'))
    OR (TASK_ID IS NOT NULL AND ACTIVE_RUNS IS NULL AND OUTCOME IS NOT NULL AND OUTCOME IN ('SUCCESS','FAILED','SKIPPED'))
);
