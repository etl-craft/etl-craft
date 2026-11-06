-- Record each validation decision on a file an event wait admitted, with the digest it was read at.
CREATE TABLE AUD_EVENT_FILE_DECISIONS (
    DECISION_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    TASK_ID BIGINT NOT NULL,
    FILE_PATH TEXT NOT NULL,
    VALIDATION_TASK_RUN_ID BIGINT NOT NULL REFERENCES AUD_TASK_RUN_LOG(TASK_RUN_ID),
    SHA256 VARCHAR(64) NOT NULL,
    SIZE_BYTES BIGINT NOT NULL,
    STATUS VARCHAR(8) NOT NULL CHECK (STATUS IN ('ACCEPTED','REFUSED')),
    REASON TEXT,
    DECIDED_AT TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now') || '000+00:00'),
    CONSTRAINT fk_event_file_decision_file FOREIGN KEY (TASK_ID, FILE_PATH)
        REFERENCES AUD_EVENT_FILES(TASK_ID, FILE_PATH),
    CONSTRAINT ck_event_file_decision_reason CHECK ((STATUS = 'REFUSED') = (REASON IS NOT NULL))
);
CREATE INDEX ix_event_file_decisions_file ON AUD_EVENT_FILE_DECISIONS (TASK_ID, FILE_PATH, DECISION_ID);
CREATE INDEX ix_event_file_decisions_run ON AUD_EVENT_FILE_DECISIONS (VALIDATION_TASK_RUN_ID);
CREATE TRIGGER trg_actor_guard_aud_event_file_decisions_insert BEFORE INSERT ON AUD_EVENT_FILE_DECISIONS
BEGIN
    SELECT CASE WHEN etl_craft_actor() IS NULL THEN RAISE(ABORT, 'AUD_EVENT_FILE_DECISIONS is written only by etl-craft') END;
END;
CREATE TRIGGER trg_actor_guard_aud_event_file_decisions_update BEFORE UPDATE ON AUD_EVENT_FILE_DECISIONS
BEGIN
    SELECT CASE WHEN etl_craft_actor() IS NULL THEN RAISE(ABORT, 'AUD_EVENT_FILE_DECISIONS is written only by etl-craft') END;
    SELECT CASE WHEN etl_craft_purpose() <> 'retention' THEN RAISE(ABORT, 'AUD_EVENT_FILE_DECISIONS immutable history; use a new action or etl-craft retention') END;
END;
CREATE TRIGGER trg_actor_guard_aud_event_file_decisions_delete BEFORE DELETE ON AUD_EVENT_FILE_DECISIONS
BEGIN
    SELECT CASE WHEN etl_craft_actor() IS NULL THEN RAISE(ABORT, 'AUD_EVENT_FILE_DECISIONS is written only by etl-craft') END;
    SELECT CASE WHEN etl_craft_purpose() <> 'retention' THEN RAISE(ABORT, 'AUD_EVENT_FILE_DECISIONS immutable history; use a new action or etl-craft retention') END;
END;
