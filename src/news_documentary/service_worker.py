"""Shared-mode worker bridge: polls the Express job queue and runs the
Python production workflow (Main Deep Agent + outer LangGraph graph).

Ownership:
- Express owns auth, job rows, leases, progress events, artifacts index.
- This worker owns agent execution, checkpoints, media files.
- Queue payloads carry job IDs + artifact refs only, never blobs.
- AI worker receives account *references*, never OAuth tokens.

Run: uv run newsdoc-worker [--api URL] [--once]
Env: API_BASE_URL, WORKER_SERVICE_TOKEN, WORKER_ID, JOB_ROOT, DB_PATH
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path


def _api(op: str, payload: dict | None = None, method: str = "GET") -> dict:
    base = os.environ.get("API_BASE_URL", "http://localhost:4000").rstrip("/")
    token = os.environ.get("WORKER_SERVICE_TOKEN", "")
    url = base + op
    data = json.dumps(payload or {}).encode() if payload is not None or method != "GET" else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "X-Service-Token": token})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode()
        return json.loads(body) if body else {}


def post_progress(job_id: str, kind: str, message: str, stage: str = "", status: str = "") -> None:
    try:
        _api(f"/api/jobs/internal/{job_id}/progress",
             {"kind": kind, "message": message, "stage": stage, "status": status,
              "data": {}}, method="POST")
    except Exception as e:
        print(f"[worker] progress post failed: {e}")


def post_artifact(job_id: str, name: str, local_path: str) -> None:
    try:
        p = Path(local_path)
        size = p.stat().st_size if p.exists() else 0
        h = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""
        _api(f"/api/jobs/internal/{job_id}/artifacts",
             {"name": name, "path": local_path, "content_type": "",
              "size_bytes": size, "sha256": h}, method="POST")
    except Exception as e:
        print(f"[worker] artifact post failed: {e}")


def run_shared_job(job: dict) -> None:
    """Execute one leased Express job. Active scope is PDF + social posts
    (doc graph — no FFmpeg/TTS/Veo). Legacy video jobs run the preserved
    video graph only when explicitly requested (local CLI)."""
    from news_documentary.config import Settings, job_dir as _job_dir
    from news_documentary.persistence import db as pdb
    from news_documentary.providers.llm import export_keys_to_env
    from news_documentary.workflow import doc_graph as D
    from news_documentary.workflow.checkpoints import checkpoint_cm

    job_id = job["job_id"]
    js = job.get("settings", {}) or {}
    job_type = (js.get("job_type") or job.get("job_type") or "report").lower()
    if job_type not in ("report", "social"):
        post_progress(job_id, "job-failed",
                      f"Unsupported job_type={job_type!r} in doc scope (report|social). "
                      "Legacy video code is preserved but disabled in active workflows.",
                      "failed", "failed")
        return
    st = Settings(
        tts_provider="fixture",  # doc jobs never synthesize audio
        video_provider="stills",  # doc jobs never render video
        job_type=job_type,
        social_platforms=",".join(js.get("platforms") or ["x", "facebook", "hikmah"]),
        narration_lang=js.get("language") or os.environ.get("NARRATION_LANG", "en"),
        revision_note=str(js.get("revision_note") or ""),
        doc_duration_seconds=int(js.get("duration_seconds") or 75),
        video_aspect=js.get("aspect_ratio") or "vertical",
        job_root=os.environ.get("JOB_ROOT", "data/jobs"),
        db_path=os.environ.get("DB_PATH", "data/newsdoc.sqlite"),
        publish_policy="manual",  # shared mode: user-controlled publish only
    )
    export_keys_to_env(st)
    pdb.migrate(st.db_path)
    topic = js.get("topic") or job.get("topic", "")
    post_progress(job_id, "research-started", f"Research started: {topic[:120]}", "research", "running")

    # Resume-capable: reuses research + fact-check when present (revisions,
    # crash recovery), otherwise runs the full doc workflow.
    with checkpoint_cm(st.db_path + ".checkpoints.sqlite") as ckpt:
        out = D.resume_doc_job(st, job_id, checkpointer=ckpt, topic=topic)

    status = out.get("status", "")
    stage = out.get("stage", "")
    # Map graph terminal states to shared statuses.
    shared_status = {
        "awaiting-approval": "awaiting-approval",
        "approved": "approved", "auto-approved": "approved",
        "ready_for_user": "ready_for_user",
        "published": "published", "blocked-no-evidence": "blocked-no-evidence",
        "reviewed-failed": "reviewed-failed",
    }.get(status, status or "awaiting-approval")

    jd = _job_dir(st.job_root, job_id)
    # Readable progress events (never ToolCallRequest dumps).
    kind_map = [
        ("research", "research-started", "Research started"),
        ("fact_check", "fact-check-completed", "Fact-check completed"),
        ("write", "write-ready", "Draft ready"),
        ("review", "review-ready", "Review ready"),
    ]
    for _, kind, msg in kind_map:
        post_progress(job_id, kind, msg, stage, shared_status)
    # Artifact refs (paths, not blobs).
    for name, fname in (("report_pdf", "report.pdf"), ("report_md", "report.md"),
                        ("posts_json", "posts.json"),
                        ("research_json", "research_notes.json"),
                        ("fact_report_json", "fact_report.json"),
                        ("review_json", "review.json")):
        p = jd / fname
        if p.exists():
            post_artifact(job_id, name, str(p))
    # Persist sources/claims into shared DB for the source viewer. Direct row
    # write works for the sqlite fallback (same file); with Postgres the API
    # serves them from job files, so skip instead of failing.
    if not os.environ.get("DATABASE_URL"):
        try:
            sync_sources_claims(st.db_path, job_id, jd)
        except Exception as e:
            print(f"[worker] source sync failed: {e}")
    post_progress(job_id, "job-finished", f"Finished: {shared_status}", stage, shared_status)


def sync_sources_claims(db_path: str, job_id: str, jd: Path) -> None:
    import sqlite3

    c = sqlite3.connect(db_path)
    try:
        c.execute("DELETE FROM sources WHERE job_id=?", (job_id,))
        c.execute("DELETE FROM claims WHERE job_id=?", (job_id,))
        try:
            sources = json.loads((jd / "sources.json").read_text(encoding="utf-8"))
        except Exception:
            sources = []
        for s in sources[:20]:
            c.execute(
                "INSERT INTO sources(job_id,url,publisher,title,published_at,updated_at,"
                "retrieved_at,event_time,excerpt,is_primary,fixture) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, s.get("url") or "", s.get("publisher") or "", (s.get("title") or "")[:300],
                 s.get("published_at") or "", s.get("updated_at") or "", s.get("retrieved_at") or "",
                 s.get("event_time") or "", (s.get("excerpt") or "")[:1000],
                 1 if s.get("is_primary") else 0, 1 if s.get("fixture") else 0))
        try:
            claims = json.loads((jd / "claims.json").read_text(encoding="utf-8"))
        except Exception:
            claims = []
        for cl in claims[:40]:
            c.execute(
                "INSERT INTO claims(job_id,claim_id,text,kind,status,source_urls,notes)"
                " VALUES(?,?,?,?,?,?,?)",
                (job_id, cl.get("id") or "", (cl.get("text") or "")[:500], cl.get("kind") or "fact",
                 cl.get("status") or "unresolved", json.dumps(cl.get("source_urls") or []),
                 (cl.get("notes") or "")[:300]))
        c.commit()
    finally:
        c.close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="newsdoc-worker")
    ap.add_argument("--api", default=os.environ.get("API_BASE_URL", "http://localhost:4000"))
    ap.add_argument("--once", action="store_true", help="claim and run a single job, then exit")
    ap.add_argument("--poll-seconds", type=float, default=5.0)
    ns = ap.parse_args()
    os.environ["API_BASE_URL"] = ns.api
    worker_id = os.environ.get("WORKER_ID", f"worker-{os.getpid()}")
    print(f"[worker] polling {ns.api} as {worker_id} (once={ns.once})")
    while True:
        try:
            res = _api("/api/jobs/internal/next", {"worker_id": worker_id}, method="POST")
        except Exception as e:
            print(f"[worker] queue poll failed: {e}; retrying in {ns.poll_seconds}s")
            if ns.once:
                return
            time.sleep(ns.poll_seconds)
            continue
        job = (res or {}).get("job")
        if not job:
            if ns.once:
                print("[worker] no queued jobs")
                return
            time.sleep(ns.poll_seconds)
            continue
        print(f"[worker] claimed {job['job_id']} ({job.get('topic','')[:80]})")
        try:
            run_shared_job(job)
        except Exception as e:
            print(f"[worker] job failed: {e}")
            post_progress(job["job_id"], "job-failed", f"Worker error: {str(e)[:300]}",
                          "failed", "failed")
        if ns.once:
            return


if __name__ == "__main__":
    main()
