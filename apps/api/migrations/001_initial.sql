-- NewsDoc shared application records v1 (owned by Express API).
-- Applied idempotently by apps/api migration runner (Postgres + sqlite fallback).
-- Python worker never migrates these tables in shared mode (see docs/queue-contracts.md).
-- SQLite and Postgres share this DDL via type mapping in the runner:
--   TEXT->TEXT, INTEGER PK AUTOINCREMENT -> SERIAL PRIMARY KEY on Postgres.

CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences(
  owner TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(owner, key)
);

CREATE TABLE IF NOT EXISTS chat_threads(
  thread_id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  owner TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  job_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs(
  job_id TEXT PRIMARY KEY,
  owner TEXT NOT NULL DEFAULT '',
  thread_id TEXT NOT NULL DEFAULT '',
  topic TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',
  stage TEXT NOT NULL DEFAULT 'discover',
  settings TEXT NOT NULL DEFAULT '{}',
  worker_id TEXT,
  lease_expires_at TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  model_calls INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  data TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, id);

CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  url TEXT NOT NULL,
  publisher TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  retrieved_at TEXT NOT NULL DEFAULT '',
  event_time TEXT NOT NULL DEFAULT '',
  excerpt TEXT NOT NULL DEFAULT '',
  is_primary INTEGER NOT NULL DEFAULT 0,
  fixture INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sources_job ON sources(job_id);

CREATE TABLE IF NOT EXISTS claims(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  claim_id TEXT NOT NULL,
  text TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'fact',
  status TEXT NOT NULL DEFAULT 'unresolved',
  source_urls TEXT NOT NULL DEFAULT '[]',
  notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_claims_job ON claims(job_id);

CREATE TABLE IF NOT EXISTS artifacts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT '',
  size_bytes INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(job_id, name)
);

CREATE TABLE IF NOT EXISTS accounts(
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  platform TEXT NOT NULL,
  label TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'connected',
  public_meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS publications(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  logical_key TEXT UNIQUE,
  job_id TEXT,
  destination TEXT,
  account_id TEXT DEFAULT '',
  owner TEXT DEFAULT '',
  artifact_hash TEXT,
  remote_id TEXT DEFAULT '',
  url TEXT DEFAULT '',
  visibility TEXT DEFAULT '',
  status TEXT DEFAULT '',
  response TEXT DEFAULT '',
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS topic_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT,
  urls TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS usage_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  owner TEXT NOT NULL DEFAULT '',
  model_calls INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
