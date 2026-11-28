UPDATE AUD_TASK_ATTEMPTS
SET FAILURE_CLASS = :failure_class, FAILURE_SOURCE = :failure_source,
    FAILURE_CODE = :failure_code, RETRYABLE = :retryable,
    FIRST_ERROR_SEQUENCE = :first_sequence,
    FIRST_ERROR_OFFSET = :first_offset,
    FIRST_ERROR_LINE = :first_line,
    FIRST_ERROR_STEP = :first_step,
    FIRST_ERROR_ERROR_CLASS = :first_error_class,
    FIRST_ERROR_EXIT_CODE = :first_exit_code,
    FIRST_ERROR_FAILURE_CLASS = :first_failure_class,
    LAST_ERROR_SEQUENCE = :last_sequence,
    LAST_ERROR_OFFSET = :last_offset,
    LAST_ERROR_LINE = :last_line,
    LAST_ERROR_STEP = :last_step,
    LAST_ERROR_ERROR_CLASS = :last_error_class,
    LAST_ERROR_EXIT_CODE = :last_exit_code,
    LAST_ERROR_FAILURE_CLASS = :last_failure_class
WHERE ATTEMPT_ID = :attempt_id AND STATUS IN ('QUEUED','CLAIMED','RUNNING')
AND (FAILURE_SOURCE IS NULL OR :overwrite)
