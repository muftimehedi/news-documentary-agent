"""Doc-scope production workflow: topic -> research -> fact_check -> write
-> review -> approval -> publish/record. No video, TTS, Veo, or FFmpeg.

- job_type=report: renders report.pdf (+ report.md); publish = record only.
- job_type=social: renders posts.json (+ report.pdf context); the worker NEVER
  uploads — connected publishing happens in Express with server-side secrets
  after explicit user review. The publish node only marks ready_for_user.

The legacy video graph (workflow/graph.py) is preserved untouched for future
use; active doc jobs never import it (no FFmpeg/gTTS/veo dependencies needed).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, TypedDict

import operator
from langgraph.graph import StateGraph, END

from ..agents.workers import run_doc_reviewer, run_factchecker, run_researcher, run_writer
from ..config import Settings, job_dir as _job_dir
from ..persistence import db as pdb
from ..providers.pdf import build_report_pdf, verify_pdf
from ..providers.search import FixtureSearchAdapter, get_search_adapter


class DocState(TypedDict, total=False):
    job_id: str
    job_type: str
    thread_id: str
    settings_snapshot: dict[str, Any]
    stage: str
    status: str
    topic: str
    sources: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    fact_report: dict[str, Any]
    summary: str
    findings: list[dict[str, Any]]
    posts: dict[str, Any]
    artifacts: dict[str, str]
    review: dict[str, Any]
    approval: dict[str, Any]
    receipts: list[dict[str, Any]]
    cost_usd: float
    model_calls: int
    attempts: Annotated[int, operator.add]
    error: str
    log: Annotated[list[str], operator.add]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(s: DocState, msg: str) -> list[str]:
    return [f"[{s.get('stage', '?')}] {msg}"]


def _settings_of(s: DocState) -> Settings:
    snap = s.get("settings_snapshot", {}) or {}
    return Settings(**{k: v for k, v in snap.items() if k in Settings.model_fields})


def _job_type_of(s: DocState) -> str:
    return s.get("job_type") or _settings_of(s).job_type or "report"


def n_discover(s: DocState) -> dict:
    st = _settings_of(s)
    adapter = get_search_adapter(st)
    try:
        items = adapter.top_news(8)
        if not items:
            raise RuntimeError("empty")
    except Exception:
        items = FixtureSearchAdapter().top_news(8)
        return {"sources": items, "stage": "choose_topic", "status": "discovered-fixture-fallback",
                "log": _log(s, f"discover: live failed, FIXTURE fallback ({len(items)} items)")}
    live = any(not i.get("fixture") for i in items)
    return {"sources": items, "stage": "choose_topic",
            "status": "discovered-live" if live else "discovered-fixture",
            "log": _log(s, f"discover: {len(items)} items via {adapter.name}")}


def n_choose_topic(s: DocState) -> dict:
    topic_hint = s.get("topic", "") or "Top Bangladesh news"
    srcs = s.get("sources", [])
    topic = topic_hint
    if srcs and not s.get("topic"):
        topic = (srcs[0].get("title", "") or topic_hint)[:140]
    return {"topic": topic, "stage": "research", "status": "topic-chosen",
            "log": _log(s, f"choose_topic: {topic[:80]}")}


def n_research(s: DocState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    topic = s.get("topic", "")
    sources = list(s.get("sources", []) or [])
    try:
        focused = get_search_adapter(st).search(topic, 8)
        seen = {x.get("url") for x in sources}
        sources += [x for x in focused if x.get("url") not in seen]
    except Exception:
        pass
    out = run_researcher(topic, sources, jd)
    (jd / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    arts = {**(s.get("artifacts", {}) or {}), "research_notes": out["notes_path"]}
    return {"topic": out["topic"], "candidates": out["candidates"], "sources": sources,
            "artifacts": arts, "stage": "fact_check", "status": "researched",
            "model_calls": (s.get("model_calls", 0) or 0) + 1,
            "log": _log(s, f"research subagent done -> {out['notes_path']}")}


def n_fact_check(s: DocState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    report = run_factchecker(s.get("topic", ""), s.get("sources", []), jd)
    arts = {**(s.get("artifacts", {}) or {}), "fact_report": str(jd / "fact_report.json")}
    if report.get("blocked"):
        return {"fact_report": report, "claims": [], "artifacts": arts, "stage": "record_result",
                "status": "blocked-no-evidence",
                "error": report.get("block_reason", "blocked"),
                "log": _log(s, "fact_check BLOCKED: no verifiable evidence")}
    return {"fact_report": report, "claims": report.get("verified", []), "artifacts": arts,
            "stage": "write", "status": "fact-checked",
            "log": _log(s, f"fact_check: {len(report.get('verified', []))} verified")}


def n_write(s: DocState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    settings_snap = s.get("settings_snapshot", {}) or {}
    revision_note = str(settings_snap.get("revision_note", "") or "")
    out = run_writer(s.get("topic", ""), s.get("fact_report", {}),
                     s.get("sources", []), st, jd, revision_note)
    fixture = not any(not x.get("fixture") for x in (s.get("sources", []) or []))
    pdf = build_report_pdf(s.get("topic", ""), out["summary"], out["findings"],
                           s.get("sources", []), s.get("fact_report", {}).get("verified", []),
                           jd / "report.pdf",
                           lang=(getattr(st, "narration_lang", "en") or "en"),
                           fixture=fixture)
    arts = {**(s.get("artifacts", {}) or {}), "report_md": str(jd / "report.md"),
            "posts": str(jd / "posts.json"), "report_pdf": pdf["path"]}
    return {"summary": out["summary"], "findings": out["findings"], "posts": out["posts"],
            "artifacts": arts, "stage": "review", "status": "written",
            "model_calls": (s.get("model_calls", 0) or 0) + 1,
            "log": _log(s, f"write v{out['version']}: report.pdf ({pdf['pages']}p) + "
                           f"{len(out['posts'])} platform posts")}


def n_review(s: DocState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    arts = s.get("artifacts", {}) or {}
    writer_out = {"summary": s.get("summary", ""), "findings": s.get("findings", []),
                  "posts": s.get("posts", {})}
    pdf_findings = verify_pdf(Path(arts["report_pdf"]), s.get("topic", "")) \
        if arts.get("report_pdf") else [{"area": "output-exists", "checked": True,
                                         "passed": False, "detail": "report.pdf missing"}]
    report = run_doc_reviewer(s.get("topic", ""), writer_out,
                              s.get("fact_report", {}), pdf_findings, jd)
    at = (s.get("attempts", 0) or 0)
    if not report["passed"] and at < st.max_retries:
        return {"review": report, "attempts": 1, "stage": "write", "status": "review-rework",
                "log": _log(s, "review FAILED -> bounded rework (write)")}
    return {"review": report, "stage": "approval",
            "status": "reviewed-passed" if report["passed"] else "reviewed-failed",
            "log": _log(s, f"review {'PASSED' if report['passed'] else 'FAILED'}: "
                           f"{len(report['findings'])} checks")}


def n_approval(s: DocState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    arts = s.get("artifacts", {}) or {}
    pdf_hash = hashlib.sha256(Path(arts["report_pdf"]).read_bytes()).hexdigest() \
        if arts.get("report_pdf") else ""
    posts_hash = hashlib.sha256(json.dumps(s.get("posts", {}), sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()
    approval_file = jd / "approval.json"
    if st.publish_policy == "auto" and s.get("review", {}).get("passed"):
        appr = {"approved": True, "pdf_hash": pdf_hash, "posts_hash": posts_hash,
                "version": 1, "by": "auto-policy", "at": _now()}
        approval_file.write_text(json.dumps(appr, indent=2), encoding="utf-8")
        return {"approval": appr, "stage": "publish", "status": "auto-approved",
                "log": _log(s, "approval: auto-policy after passed review")}
    if approval_file.exists():
        appr = json.loads(approval_file.read_text(encoding="utf-8"))
        if appr.get("pdf_hash") == pdf_hash and appr.get("posts_hash") == posts_hash:
            return {"approval": appr, "stage": "publish", "status": "approved",
                    "log": _log(s, "approval: operator approval valid")}
        return {"approval": {"approved": False}, "stage": "approval", "status": "approval-stale",
                "log": _log(s, "approval: output changed -> earlier approval INVALID")}
    return {"approval": {"approved": False, "pdf_hash": pdf_hash, "posts_hash": posts_hash,
                         "pending": True},
            "stage": "approval", "status": "awaiting-approval",
            "log": _log(s, "approval: PAUSED for operator (UI/CLI approve)")}


def n_publish(s: DocState) -> dict:
    """Ready gate. The worker never uploads: report jobs finish here; social
    jobs wait for explicit user publishing in Express (server-side secrets)."""
    st = _settings_of(s)
    jt = _job_type_of(s)
    appr = s.get("approval", {}) or {}
    if jt == "social" and not appr.get("approved"):
        return {"stage": "approval", "status": "awaiting-approval",
                "log": _log(s, "publish: social text waits for explicit user publish")}
    pdb.upsert_job(st.db_path, s["job_id"], s.get("thread_id", ""), s.get("topic", ""),
                   "ready" if jt == "social" else "published", s.get("settings_snapshot", {}))
    return {"receipts": [], "stage": "record_result",
            "status": "ready_for_user" if jt == "social" else "published",
            "log": _log(s, f"publish: {jt} ready (no worker-side upload)")}


def n_record(s: DocState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    summary = {"job_id": s.get("job_id"), "job_type": _job_type_of(s),
               "topic": s.get("topic"), "status": s.get("status"),
               "artifacts": s.get("artifacts", {}), "receipts": s.get("receipts", []),
               "review": s.get("review", {}), "cost_usd": s.get("cost_usd", 0.0),
               "model_calls": s.get("model_calls", 0), "at": _now()}
    (jd / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pdb.upsert_job(st.db_path, s["job_id"], s.get("thread_id", ""), s.get("topic", ""),
                   s.get("status", "done"), s.get("settings_snapshot", {}))
    return {"stage": "done", "status": s.get("status", "done"), "log": _log(s, "record_result: done")}


def build_doc_graph(checkpointer=None):
    g = StateGraph(DocState)
    g.add_node("discover", n_discover)
    g.add_node("choose_topic", n_choose_topic)
    g.add_node("research", n_research)
    g.add_node("fact_check", n_fact_check)
    g.add_node("write", n_write)
    g.add_node("review", n_review)
    g.add_node("approval", n_approval)
    g.add_node("publish", n_publish)
    g.add_node("record_result", n_record)
    g.set_entry_point("discover")
    g.add_edge("discover", "choose_topic")
    g.add_edge("choose_topic", "research")
    g.add_edge("research", "fact_check")

    def after_fact(s: DocState) -> str:
        return "record_result" if s.get("stage") == "record_result" else "write"
    g.add_conditional_edges("fact_check", after_fact,
                            {"record_result": "record_result", "write": "write"})
    g.add_edge("write", "review")

    def after_review(s: DocState) -> str:
        return "write" if s.get("stage") == "write" else "approval"
    g.add_conditional_edges("review", after_review, {"write": "write", "approval": "approval"})

    def after_approval(s: DocState) -> str:
        return "publish" if s.get("status") in ("approved", "auto-approved") else "wait"
    g.add_conditional_edges("approval", after_approval, {"publish": "publish", "wait": END})
    g.add_edge("publish", "record_result")
    g.add_edge("record_result", END)
    return g.compile(checkpointer=checkpointer)


def initial_doc_state(job_id: str, settings: Settings, topic: str = "",
                      job_type: str = "report") -> DocState:
    snap = settings.model_dump()
    snap["revision_note"] = getattr(settings, "revision_note", "") or ""
    return {"job_id": job_id, "job_type": job_type, "thread_id": f"thread-{job_id}",
            "settings_snapshot": snap, "stage": "discover", "status": "started",
            "topic": topic, "sources": [], "candidates": [], "claims": [],
            "cost_usd": 0.0, "model_calls": 0, "attempts": 0, "receipts": [],
            "artifacts": {}, "log": []}


def run_doc_job(settings: Settings, topic: str = "", job_type: str = "report",
                job_id: str | None = None, checkpointer=None,
                revision_note: str = "") -> dict:
    """Doc entrypoint (local + worker). No FFmpeg/TTS/Veo imports anywhere."""
    from .checkpoints import checkpoint_cm
    from ..providers.llm import export_keys_to_env

    pdb.migrate(settings.db_path)
    export_keys_to_env(settings)
    jid = job_id or f"job-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": f"thread-{jid}"}}
    state = initial_doc_state(jid, settings, topic, job_type)
    if revision_note:
        state["settings_snapshot"]["revision_note"] = revision_note
    if checkpointer is not None:
        return build_doc_graph(checkpointer).invoke(state, config=cfg)
    with checkpoint_cm(settings.db_path + ".checkpoints.sqlite") as ckpt:
        return build_doc_graph(ckpt).invoke(state, config=cfg)


def build_doc_resume_graph(checkpointer=None):
    """Resume from write: reuses persisted research + fact-check artifacts.
    Used for explicit user revisions (cheap) and crash recovery."""
    g = StateGraph(DocState)
    g.add_node("write", n_write)
    g.add_node("review", n_review)
    g.add_node("approval", n_approval)
    g.add_node("publish", n_publish)
    g.add_node("record_result", n_record)
    g.set_entry_point("write")
    g.add_edge("write", "review")

    def after_review(s: DocState) -> str:
        return "write" if s.get("stage") == "write" else "approval"
    g.add_conditional_edges("review", after_review, {"write": "write", "approval": "approval"})

    def after_approval(s: DocState) -> str:
        return "publish" if s.get("status") in ("approved", "auto-approved") else "wait"
    g.add_conditional_edges("approval", after_approval, {"publish": "publish", "wait": END})
    g.add_edge("publish", "record_result")
    g.add_edge("record_result", END)
    return g.compile(checkpointer=checkpointer)


def resume_doc_job(settings: Settings, job_id: str, checkpointer=None,
                   topic: str = "") -> dict:
    """Restart-safe resume: reuse sources + fact report, rerun write->review.
    Falls back to a full run when research artifacts are missing."""
    from .checkpoints import checkpoint_cm
    from ..providers.llm import export_keys_to_env

    pdb.migrate(settings.db_path)
    export_keys_to_env(settings)
    jd = _job_dir(settings.job_root, job_id)
    cfg = {"configurable": {"thread_id": f"thread-{job_id}"}}
    has_research = (jd / "sources.json").exists() and (jd / "fact_report.json").exists()
    if has_research:
        state: DocState = initial_doc_state(job_id, settings, "")
        try:
            srcs = json.loads((jd / "sources.json").read_text(encoding="utf-8"))
            frep = json.loads((jd / "fact_report.json").read_text(encoding="utf-8"))
            state["sources"] = srcs
            state["fact_report"] = frep
            state["claims"] = frep.get("verified", [])
            state["topic"] = state.get("topic", "") or ""
            # recover topic from research notes when available
            try:
                notes = json.loads((jd / "research_notes.json").read_text(encoding="utf-8"))
                state["topic"] = notes.get("topic_hint") or state["topic"]
                state["candidates"] = notes.get("candidates", [])
            except Exception:
                pass
            state["stage"] = "write"
            state["status"] = "resumed"
        except Exception:
            has_research = False
    if not has_research:
        return run_doc_job(settings, topic, getattr(settings, "job_type", "report"),
                           job_id, checkpointer=checkpointer)
    if checkpointer is not None:
        return build_doc_resume_graph(checkpointer).invoke(state, config=cfg)
    with checkpoint_cm(settings.db_path + ".checkpoints.sqlite") as ckpt:
        return build_doc_resume_graph(ckpt).invoke(state, config=cfg)
