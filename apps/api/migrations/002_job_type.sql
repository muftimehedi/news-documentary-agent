-- Doc scope: job_type for report/social jobs. Legacy video rows keep working
-- (video columns were never in this table; video state lives in job files).
-- Applied once via schema_migrations; safe on both Postgres and sqlite.
ALTER TABLE jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'report';
