-- What may start runs by itself in a project, as Orchestration.Allowed_auto_restarts does for a whole controller: the narrower of the two applies.
ALTER TABLE CFG_PROJECTS ADD COLUMN ALLOWED_AUTO_RESTARTS VARCHAR NOT NULL DEFAULT 'SCHEDULE|ALWAYS'
    CHECK (length(ALLOWED_AUTO_RESTARTS) > 0 AND ALLOWED_AUTO_RESTARTS NOT GLOB '*[^A-Z|]*');
