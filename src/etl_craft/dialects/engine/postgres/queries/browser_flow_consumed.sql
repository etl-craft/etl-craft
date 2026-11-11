SELECT COUNT(*) AS count FROM AUD_ACTIONS
WHERE ACTOR=:actor AND ACTION_ID>:issued_id AND COMMAND='login' AND OUTCOME='SUCCESS'
AND ARGUMENTS->>'browser_flow'=:digest AND ARGUMENTS->>'phase'='consumed'
