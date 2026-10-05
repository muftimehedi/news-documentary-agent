"""Publish manager: idempotency, backoff, partial-resume, reconciliation."""
from __future__ import annotations

import time
from pathlib import Path

from ..persistence import db as pdb
from .youtube import get_publisher


def logical_key(job_id: str, destination: str, artifact_hash: str) -> str:
    return f"{job_id}:{destination}:{artifact_hash[:16]}"


def publish_with_reconciliation(settings, db_path: str, job_id: str, destination: str,
                                video: Path, title: str, description: str, visibility: str,
                                artifact_hash: str) -> dict:
    key = logical_key(job_id, destination, artifact_hash)
    existing = pdb.get_publication(db_path, key)
    if existing and existing.get("status", "").startswith("succeeded"):
        return {"skipped": True, "reason": "already-succeeded", "key": key, **existing}
    if existing is None:
        claimed = pdb.claim_publication_slot(db_path, key, job_id, destination, artifact_hash)
        if not claimed:
            existing = pdb.get_publication(db_path, key)
            if existing and existing.get("status", "").startswith("succeeded"):
                return {"skipped": True, "reason": "already-succeeded", "key": key, **existing}
    else:
        # A prior intent without success: reconcile before retrying.
        if existing.get("status") == "unknown-timeout":
            return {"skipped": True, "reason": "needs-operator-resolution", "key": key, **existing}

    pub = get_publisher(settings, destination)
    try:
        receipt = pub.upload(video, title, description, visibility)
        pdb.record_receipt(db_path, key, receipt)
        return {"skipped": False, "key": key, **receipt}
    except TimeoutError as e:
        pdb.record_receipt(db_path, key, {"remote_id": "", "url": "", "visibility": visibility,
                                          "status": "unknown-timeout",
                                          "timestamp": "", "fixture": False,
                                          "note": f"ambiguous timeout, do NOT blind-retry: {e}"})
        return {"skipped": True, "reason": "unknown-timeout", "key": key}
    except Exception as e:
        msg = str(e)
        permanent = any(k in msg for k in ("invalid_grant", "invalid_client", "NOT implemented",
                                           "missing", "validation", "HttpError 40"))
        pdb.record_receipt(db_path, key, {"remote_id": "", "url": "", "visibility": visibility,
                                          "status": "failed-permanent" if permanent else "failed-retryable",
                                          "timestamp": "", "fixture": False, "note": msg[:500]})
        raise
