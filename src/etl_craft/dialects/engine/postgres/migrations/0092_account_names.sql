-- An account's name as its person writes it, kept apart from the sign-in name and filled from SSO claims.
ALTER TABLE CFG_ACCOUNTS ADD COLUMN FIRST_NAME VARCHAR(128);
ALTER TABLE CFG_ACCOUNTS ADD COLUMN LAST_NAME VARCHAR(128);
