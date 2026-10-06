"""Connected publishing service: review binding + reliable multi-destination upload.

Flow (explicit user actions only; connecting an account NEVER publishes):
  1. User edits title/description -> saved to publish_meta.json (draft, not authorized).
  2. User clicks "Review & authorize" -> build_review() snapshots video hash +
     script version + full metadata + destination accounts into publish_review.json
     and binds approval.json to the same metadata_hash.
  3. User clicks "Publish" -> publish_reviewed() re-verifies the snapshot against
     the CURRENT files. Any change to video or settings -> blocked, new review needed.
  4. Each destination uploads independently; failures never erase other results;
     retry_failed() re-runs only non-succeeded destinations without re-uploading wins.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..persistence import db as pdb
from ..persistence import vault as V
from .adapters import AdapterError, get_adapter


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def job_paths(job_root: str, job_id: str) -> dict[str, Path]:
    jd = Path(job_root) / job_id
    return {"dir": jd, "video": jd / "documentary.mp4", "script": jd / "script.json",
            "meta": jd / "publish_meta.json", "review": jd / "publish_review.json",
            "approval": jd / "approval.json", "sources": jd / "sources.json"}


def default_meta(job_root: str, job_id: str) -> dict:
    """Draft metadata: publish_meta.json if the user edited it, else script/sources defaults."""
    jp = job_paths(job_root, job_id)
    if jp["meta"].exists():
        try:
            return json.loads(jp["meta"].read_text(encoding="utf-8"))
        except Exception:
            pass
    title, desc = job_id, ""
    if jp["script"].exists():
        s = json.loads(jp["script"].read_text(encoding="utf-8"))
        title = s.get("title", title)[:100]
        desc = (s.get("narration_full", "")[:1500])
    links: list[str] = []
    if jp["sources"].exists():
        try:
            links = [x.get("url", "") for x in json.loads(jp["sources"].read_text(encoding="utf-8"))[:8]]
        except Exception:
            pass
    return {"title": title, "description": desc, "source_links": links}


def save_meta(job_root: str, owner: str, job_id: str, title: str, description: str) -> dict:
    jp = job_paths(job_root, job_id)
    meta = {**default_meta(job_root, job_id), "title": title[:200], "description": description[:5000],
            "edited_by": owner, "edited_at": _now()}
    jp["meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def metadata_hash(title: str, description: str, selections: list[dict]) -> str:
    norm = json.dumps({"title": title, "description": description,
                       "destinations": sorted(
                           (s.get("account_id", ""), s.get("platform", ""), s.get("visibility", ""))
                           for s in selections)}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def build_review(db_path: str, owner: str, job_root: str, job_id: str,
                 selections: list[dict]) -> dict:
    """Authorize exactly this video + metadata + destinations. Returns the review snapshot."""
    jp = job_paths(job_root, job_id)
    if not jp["video"].exists():
        raise AdapterError("No rendered video for this job yet.", permanent=True)
    meta = default_meta(job_root, job_id)
    sels: list[dict] = []
    for s in selections:
        acc = V.get_account(db_path, owner, s.get("account_id", ""))
        if not acc or acc["status"] != "connected":
            raise AdapterError(f"Account {s.get('account_id')} is not connected (owner-scoped).",
                               permanent=True)
        vis = s.get("visibility", "public")
        adapter = get_adapter(acc["platform"])
        errs = adapter.validate(jp["video"], meta["title"], meta.get("description", ""), vis)
        if errs:
            raise AdapterError(f"{acc['platform']} validation: {'; '.join(errs)}", permanent=True)
        sels.append({"account_id": acc["id"], "platform": acc["platform"],
                     "label": acc["label"], "visibility": vis})
    if not sels:
        raise AdapterError("Select at least one connected account.", permanent=True)
    try:
        script = json.loads(jp["script"].read_text(encoding="utf-8"))
        script_version = script.get("version", 1)
    except Exception:
        script_version = 1
    review = {"job_id": job_id, "owner": owner, "video_hash": sha256_file(jp["video"]),
              "script_version": script_version, "title": meta["title"],
              "description": meta.get("description", ""), "source_links": meta.get("source_links", []),
              "selections": sels,
              "metadata_hash": metadata_hash(meta["title"], meta.get("description", ""), sels),
              "reviewed_by": owner, "reviewed_at": _now()}
    jp["review"].write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    appr = {"approved": True, "video_hash": review["video_hash"],
            "script_version": script_version, "metadata_hash": review["metadata_hash"],
            "destinations": [f"{s['platform']}:{s['account_id']}" for s in sels],
            "by": owner, "at": review["reviewed_at"]}
    jp["approval"].write_text(json.dumps(appr, indent=2), encoding="utf-8")
    return review


def _get_pub(db_path: str, key: str) -> dict | None:
    return pdb.get_publication(db_path, key)


def _claim(db_path: str, key: str, job_id: str, dest: str, ahash: str,
           account_id: str, owner: str) -> bool:
    ok = pdb.claim_publication_slot(db_path, key, job_id, dest, ahash)
    c = pdb.connect(db_path)
    c.execute("UPDATE publications SET account_id=?,owner=? WHERE logical_key=?",
              (account_id, owner, key))
    c.commit(); c.close()
    return ok


def _record(db_path: str, key: str, receipt: dict) -> None:
    pdb.record_receipt(db_path, key, receipt)


def _upload_one(db_path: str, owner: str, review: dict, sel: dict, video: Path) -> dict:
    key = f"{review['job_id']}:{sel['account_id']}:{review['video_hash'][:16]}"
    existing = _get_pub(db_path, key)
    if existing and str(existing.get("status", "")).startswith("succeeded"):
        return {"account_id": sel["account_id"], "platform": sel["platform"],
                "skipped": True, "reason": "already-succeeded", **existing}
    if existing and existing.get("status") == "unknown-timeout":
        return {"account_id": sel["account_id"], "platform": sel["platform"],
                "skipped": True, "reason": "needs-operator-resolution", **existing}
    if existing is None:
        if not _claim(db_path, key, review["job_id"], sel["platform"], review["video_hash"],
                      sel["account_id"], owner):
            existing = _get_pub(db_path, key)
            if existing and str(existing.get("status", "")).startswith("succeeded"):
                return {"account_id": sel["account_id"], "platform": sel["platform"],
                        "skipped": True, "reason": "already-succeeded", **existing}
    acc = V.get_account(db_path, owner, sel["account_id"])
    if not acc or acc["status"] != "connected":
        res = {"destination": sel["platform"], "status": "failed-permanent",
               "note": "account disconnected before upload", "fixture": False}
        _record(db_path, key, res)
        return {"account_id": sel["account_id"], "platform": sel["platform"], **res}
    try:
        secret = V.load_secret(db_path, sel["account_id"])
    except Exception as e:
        res = {"destination": sel["platform"], "status": "failed-permanent",
               "note": f"credential unavailable: {e}", "fixture": False}
        _record(db_path, key, res)
        return {"account_id": sel["account_id"], "platform": sel["platform"], **res}
    adapter = get_adapter(sel["platform"])
    try:
        receipt = adapter.upload(video, review["title"], review["description"],
                                 sel["visibility"], secret, job_id=review["job_id"])
        _record(db_path, key, receipt)
        return {"account_id": sel["account_id"], "platform": sel["platform"],
                "skipped": False, **receipt}
    except AdapterError as e:
        status = "failed-permanent" if e.permanent else "failed-retryable"
        res = {"destination": sel["platform"], "status": status,
               "note": str(e)[:400], "fixture": False}
        _record(db_path, key, res)
        return {"account_id": sel["account_id"], "platform": sel["platform"], **res}
    except Exception as e:  # ambiguous (e.g. timeout with unknown outcome): never blind-retry
        res = {"destination": sel["platform"], "status": "unknown-timeout",
               "note": f"ambiguous failure, needs operator resolution: {str(e)[:300]}",
               "fixture": False}
        _record(db_path, key, res)
        return {"account_id": sel["account_id"], "platform": sel["platform"], **res}


def publish_reviewed(db_path: str, owner: str, job_root: str, job_id: str) -> list[dict]:
    """Publish ONLY the reviewed artifact to the reviewed destinations.
    Independent per-destination results; one failure never erases other successes."""
    jp = job_paths(job_root, job_id)
    if not jp["review"].exists():
        raise AdapterError("No review found. Review & authorize before publishing.", permanent=True)
    review = json.loads(jp["review"].read_text(encoding="utf-8"))
    if review.get("owner") != owner:
        raise AdapterError("Review belongs to another owner.", permanent=True)
    if not jp["video"].exists():
        raise AdapterError("Reviewed video file is missing.", permanent=True)
    if sha256_file(jp["video"]) != review.get("video_hash"):
        raise AdapterError("Video changed after review — authorize a new review first.", permanent=True)
    meta = default_meta(job_root, job_id)
    if metadata_hash(meta["title"], meta.get("description", ""), review.get("selections", [])) != review.get("metadata_hash"):
        raise AdapterError("Title/description/destinations changed after review — authorize again.",
                           permanent=True)
    results: list[dict] = []
    for sel in review.get("selections", []):
        # bounded retries for retryable failures only
        attempt, res = 0, None
        while True:
            res = _upload_one(db_path, owner, review, sel, jp["video"])
            if res.get("status") == "failed-retryable" and attempt < 2 and not res.get("skipped"):
                attempt += 1
                time.sleep(min(20, 2 ** attempt))
                continue
            break
        results.append(res)
    pdb.upsert_job(db_path, job_id, f"thread-{job_id}", review.get("title", job_id),
                   "published" if any(str(r.get("status", "")).startswith("succeeded") for r in results)
                   else "publish-partial-or-failed",
                   {"owner": owner})
    return results


def retry_failed(db_path: str, owner: str, job_root: str, job_id: str) -> list[dict]:
    """Re-run only non-succeeded destinations; successful uploads are never repeated."""
    return publish_reviewed(db_path, owner, job_root, job_id)
