-- The controller records the Orchestration.Allowed_auto_restarts it runs with, so what suppresses scheduled and automatic starts is visible.
ALTER TABLE AUD_CONTROLLERS ADD COLUMN ALLOWED_AUTO_RESTARTS VARCHAR NOT NULL DEFAULT 'SCHEDULE|ALWAYS';
