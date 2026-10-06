"""Durable local persistence: sqlite domain records + JSON job files.
Checkpoints (short-term) vs store (long-term) vs files (large media) stay separate."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def migrate(db_path: str) -> None:
    c = connect(db_path)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(
      job_id TEXT PRIMARY KEY, thread_id TEXT, topic TEXT, status TEXT,
      settings TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS publications(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      logical_key TEXT UNIQUE, job_id TEXT, destination TEXT, artifact_hash TEXT,
      remote_id TEXT, url TEXT, visibility TEXT, status TEXT, response TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS topic_history(
      id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, urls TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS preferences(
      key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS accounts(
      id TEXT PRIMARY KEY, owner TEXT NOT NULL, platform TEXT NOT NULL,
      label TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'connected',
      public_meta TEXT NOT NULL DEFAULT '{}',
      created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS publications(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      logical_key TEXT UNIQUE, job_id TEXT, destination TEXT, artifact_hash TEXT,
      remote_id TEXT, url TEXT, visibility TEXT, status TEXT, response TEXT, created_at TEXT);
    """)
    for col in ("account_id TEXT DEFAULT ''", "owner TEXT DEFAULT ''"):
        try:
            c.execute(f"ALTER TABLE publications ADD COLUMN {col}")
        except Exception:
            pass
    c.commit(); c.close()


def upsert_job(db_path: str, job_id: str, thread_id: str, topic: str, status: str, settings: dict) -> None:
    c = connect(db_path)
    c.execute("INSERT INTO jobs(job_id,thread_id,topic,status,settings,updated_at) VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(job_id) DO UPDATE SET topic=excluded.topic,status=excluded.status,"
              "settings=excluded.settings,updated_at=excluded.updated_at",
              (job_id, thread_id, topic, status, json.dumps(settings, ensure_ascii=False),
               datetime.now(timezone.utc).isoformat()))
    c.commit(); c.close()


def claim_publication_slot(db_path: str, logical_key: str, job_id: str, destination: str,
                           artifact_hash: str) -> bool:
    """Idempotency: UNIQUE(logical_key). Returns False if already published (duplicate prevention)."""
    c = connect(db_path)
    try:
        c.execute("INSERT INTO publications(logical_key,job_id,destination,artifact_hash,status,created_at)"
                  " VALUES(?,?,?,?,?,?)",
                  (logical_key, job_id, destination, artifact_hash, "intent",
                   datetime.now(timezone.utc).isoformat()))
        c.commit(); return True
    except sqlite3.IntegrityError:
        return False
    finally:
        c.close()


def record_receipt(db_path: str, logical_key: str, receipt: dict) -> None:
    c = connect(db_path)
    c.execute("UPDATE publications SET remote_id=?,url=?,visibility=?,status=?,response=? WHERE logical_key=?",
              (receipt.get("remote_id", ""), receipt.get("url", ""), receipt.get("visibility", ""),
               receipt.get("status", ""), json.dumps(receipt, ensure_ascii=False), logical_key))
    c.commit(); c.close()


def get_publication(db_path: str, logical_key: str) -> dict | None:
    c = connect(db_path)
    r = c.execute("SELECT remote_id,url,visibility,status,response FROM publications WHERE logical_key=?",
                  (logical_key,)).fetchone()
    c.close()
    if not r:
        return None
    return {"remote_id": r[0], "url": r[1], "visibility": r[2], "status": r[3], "response": r[4]}
