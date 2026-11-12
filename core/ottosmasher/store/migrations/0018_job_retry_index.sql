-- SQLite checks the self-reference for every deleted job. Index the sparse retry links.
CREATE INDEX job_retry_of ON job(retry_of) WHERE retry_of IS NOT NULL;
