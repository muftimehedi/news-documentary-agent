"""Outer production LangGraph workflow (typed state, checkpoints, approval gate).

Chain: discover -> choose_topic -> research -> fact_check -> script -> prepare_media
       -> render -> review -> approval -> publish -> record_result
with bounded correction branches (fact-check fail / review fail -> revise, max N).
Graph owns stage transitions + side effects; Main Deep Agent owns planning/research/delegation.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langgraph.graph import StateGraph, END

from ..agents.workers import run_researcher, run_factchecker, run_scriptwriter
from ..config import Settings, job_dir as _job_dir
from ..media.video import write_srt, render_documentary, verify_media
from ..persistence import db as pdb
from ..providers.assets import make_still
from ..providers.search import get_search_adapter, FixtureSearchAdapter
from ..providers.tts import get_tts_adapter
from ..publishing.manager_helpers import publish_with_reconciliation
from ..schemas import JobState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(s: JobState, msg: str) -> list[str]:
    return [f"[{s.get('stage', '?')}] {msg}"]


def _settings_of(s: JobState) -> Settings:
    snap = s.get("settings_snapshot", {}) or {}
    return Settings(**{k: v for k, v in snap.items() if k in Settings.model_fields})


def n_discover(s: JobState) -> dict:
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


def n_choose_topic(s: JobState) -> dict:
    topic_hint = s.get("topic", "") or "Top Bangladesh news"
    srcs = s.get("sources", [])
    # duplicate-topic guard via URL + title similarity against history could go here;
    # keep simple: prefer first source title.
    topic = topic_hint
    if srcs and not s.get("topic"):
        topic = (srcs[0].get("title", "") or topic_hint)[:140]
    return {"topic": topic, "stage": "research", "status": "topic-chosen",
            "log": _log(s, f"choose_topic: {topic[:80]}")}


def n_research(s: JobState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    topic = s.get("topic", "")
    sources = list(s.get("sources", []) or [])
    # Focused follow-up search on the chosen topic so fact-check has
    # genuinely comparable sources (top-news feeds are often unrelated).
    try:
        focused = get_search_adapter(st).search(topic, 8)
        seen = {x.get("url") for x in sources}
        sources += [x for x in focused if x.get("url") not in seen]
    except Exception:
        pass
    out = run_researcher(topic, sources, jd)
    (jd / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    arts = {**(s.get("artifacts", {}) or {}), "research_notes": out["notes_path"]}
    return {"topic": out["topic"], "candidates": out["candidates"], "sources": sources, "artifacts": arts,
            "stage": "fact_check", "status": "researched",
            "model_calls": (s.get("model_calls", 0) or 0) + 1,
            "log": _log(s, f"research subagent done -> {out['notes_path']}")}


def n_fact_check(s: JobState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    report = run_factchecker(s.get("topic", ""), s.get("sources", []), jd)
    arts = {**(s.get("artifacts", {}) or {}), "fact_report": str(jd / "fact_report.json")}
    if report.get("blocked"):
        return {"fact_report": report, "claims": [], "artifacts": arts, "stage": "record_result",
                "status": "blocked-no-evidence",
                "error": report.get("block_reason", "blocked"),
                "log": _log(s, "fact_check BLOCKED: no verifiable evidence")}
    at = (s.get("attempts", 0) or 0)
    return {"fact_report": report, "claims": report.get("verified", []), "artifacts": arts,
            "stage": "script", "status": "fact-checked",
            "log": _log(s, f"fact_check: {len(report.get('verified', []))} verified")}


def n_script(s: JobState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    script = run_scriptwriter(s.get("topic", ""), s.get("fact_report", {}), st, jd)
    arts = {**(s.get("artifacts", {}) or {}), "script": str(jd / "script.json")}
    return {"script": script, "scenes": script["scenes"], "artifacts": arts,
            "stage": "prepare_media", "status": "scripted",
            "log": _log(s, f"script v{script['version']}: {len(script['scenes'])} scenes")}


def n_prepare_media(s: JobState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    script = s.get("script", {}) or json.loads((jd / "script.json").read_text(encoding="utf-8"))
    tts = get_tts_adapter(st.tts_provider)
    audio = tts.synthesize(script["narration_full"], script.get("language", "en"), jd / "narration.wav")
    stills = []
    assets_meta = []
    for i, sc in enumerate(script["scenes"]):
        p = jd / f"still_{i}.png"
        meta = make_still(p, sc.get("on_screen_text", "News"), st.dimensions, i)
        stills.append(str(p))
        assets_meta.append(meta)
        sc["asset"] = str(p)
    total = float(audio["duration_s"])
    per = total / max(1, len(script["scenes"]))
    for sc in script["scenes"]:
        sc["duration_s"] = round(per, 2)
    srt = write_srt(script["scenes"], total, jd / "captions.srt")
    manifest = {"audio": audio, "stills": stills, "srt": str(srt), "size": list(st.dimensions)}
    (jd / "render_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    arts = {**(s.get("artifacts", {}) or {}), "audio": audio["path"], "captions": str(srt),
            "manifest": str(jd / "render_manifest.json")}
    return {"scenes": script["scenes"], "assets": {"audio": audio, "stills": stills, "meta": assets_meta},
            "artifacts": arts, "stage": "render", "status": "media-prepared",
            "cost_usd": (s.get("cost_usd", 0.0) or 0.0) + (0.0 if audio.get("fixture") else 0.05),
            "log": _log(s, f"media: tts={tts.name} {total:.1f}s, {len(stills)} stills")}


def n_render(s: JobState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    arts = s.get("artifacts", {}) or {}
    man = json.loads((jd / "render_manifest.json").read_text(encoding="utf-8"))
    meta = render_documentary(jd, s.get("scenes", []), Path(man["audio"]["path"]),
                              tuple(st.dimensions), Path(man["srt"]), [Path(p) for p in man["stills"]],
                              lang=(s.get("script", {}) or {}).get("language", "en"))
    arts = {**arts, "video": meta["video"], "thumbnail": meta["thumbnail"]}
    return {"artifacts": arts, "assets": {**(s.get("assets", {}) or {}), "render_meta": meta},
            "stage": "review", "status": "rendered",
            "log": _log(s, f"render: {meta['video']} ({meta['duration_s']:.1f}s)")}


def n_review(s: JobState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    arts = s.get("artifacts", {}) or {}
    findings = verify_media(Path(arts["video"]), Path(arts["captions"]), Path(arts["audio"]), st.dimensions)
    # factual consistency: every scene claim id present in verified set
    verified_ids = {c.get("id") for c in (s.get("claims", []) or [])}
    bad = [sc.get("index") for sc in (s.get("scenes", []) or [])
           if any(cid not in verified_ids for cid in sc.get("claim_ids", []))]
    if bad:
        findings.append({"area": "factual-consistency", "checked": True, "passed": False,
                         "detail": f"scenes {bad} cite claims outside verified set"})
    else:
        findings.append({"area": "factual-consistency", "checked": True, "passed": True,
                         "detail": f"{len(verified_ids)} verified claim ids cover all scenes"})
    # pronunciation: flag risky tokens we cannot verify
    risky = [w for w in (s.get("script", {}) or {}).get("narration_full", "").split() if w.isupper() and len(w) > 3]
    findings.append({"area": "pronunciation", "checked": bool(risky), "passed": True,
                     "detail": f"flagged {risky[:5]} (cannot auto-verify prosody)" if risky else "no all-caps loanwords; prosody not auto-verifiable"})
    passed = all(f["passed"] for f in findings if f["checked"])
    at = (s.get("attempts", 0) or 0)
    report = {"passed": passed, "findings": findings, "needs_revision": "" if passed else "fix flagged areas"}
    (jd / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not passed and at < st.max_retries:
        return {"review": report, "attempts": 1, "stage": "prepare_media", "status": "review-rework",
                "log": _log(s, "review FAILED -> bounded rework (prepare_media)")}
    return {"review": report, "stage": "approval", "status": "reviewed-passed" if passed else "reviewed-failed",
            "log": _log(s, f"review {'PASSED' if passed else 'FAILED'}: {len(findings)} checks")}


def n_approval(s: JobState) -> dict:
    """Approval pause (interrupt). Binds approval to video hash + script version + destinations.
    Changing an approved artifact invalidates approval (checked again in publish)."""
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    vh = hashlib.sha256(Path(s["artifacts"]["video"]).read_bytes()).hexdigest()
    script = s.get("script", {}) or {}
    approval_file = jd / "approval.json"
    if st.publish_policy == "auto" and s.get("review", {}).get("passed"):
        appr = {"approved": True, "video_hash": vh, "script_version": script.get("version", 1),
                "destinations": ["youtube"], "by": "auto-policy", "at": _now()}
        approval_file.write_text(json.dumps(appr, indent=2), encoding="utf-8")
        return {"approval": appr, "stage": "publish", "status": "auto-approved",
                "log": _log(s, "approval: auto-policy after passed review")}
    if approval_file.exists():
        appr = json.loads(approval_file.read_text(encoding="utf-8"))
        if appr.get("video_hash") == vh and appr.get("script_version") == script.get("version", 1):
            return {"approval": appr, "stage": "publish", "status": "approved",
                    "log": _log(s, "approval: operator approval valid")}
        return {"approval": {"approved": False}, "stage": "approval", "status": "approval-stale",
                "log": _log(s, "approval: artifact changed -> earlier approval INVALID")}
    # pause for operator; survives restarts because state is checkpointed + approval.json on disk
    return {"approval": {"approved": False, "video_hash": vh, "pending": True},
            "stage": "approval", "status": "awaiting-approval",
            "log": _log(s, "approval: PAUSED for operator (Streamlit/CLI approve)")}


def n_publish(s: JobState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    video = Path(s["artifacts"]["video"])
    vh = hashlib.sha256(video.read_bytes()).hexdigest()
    appr = s.get("approval", {}) or {}
    if not appr.get("approved") or appr.get("video_hash") != vh:
        return {"stage": "approval", "status": "publish-blocked-no-approval",
                "error": "Publish blocked: no valid approval for this video hash.",
                "log": _log(s, "publish BLOCKED without approval")}
    script = s.get("script", {}) or {}
    desc = (script.get("narration_full", "")[:500] + "\n\nSources:\n" +
            "\n".join(x.get("url", "") for x in (s.get("sources", [])[:5])))[:4000]
    receipts = list(s.get("receipts", []) or [])
    for dest in appr.get("destinations", ["youtube"]):
        if any(r.get("destination") == dest and str(r.get("status", "")).startswith("succeeded") for r in receipts):
            continue  # resume: skip successful destinations
        r = publish_with_reconciliation(st, st.db_path, s["job_id"], dest, video,
                                        script.get("title", "News documentary")[:100],
                                        desc, st.youtube_visibility, vh)
        receipts.append(r)
    pdb.upsert_job(st.db_path, s["job_id"], s.get("thread_id", ""), s.get("topic", ""), "published",
                   s.get("settings_snapshot", {}))
    return {"receipts": receipts, "stage": "record_result", "status": "published",
            "log": _log(s, f"publish: {len(receipts)} receipts")}


def n_record(s: JobState) -> dict:
    st = _settings_of(s)
    jd = _job_dir(st.job_root, s["job_id"])
    summary = {"job_id": s.get("job_id"), "topic": s.get("topic"), "status": s.get("status"),
               "artifacts": s.get("artifacts", {}), "receipts": s.get("receipts", []),
               "review": s.get("review", {}), "cost_usd": s.get("cost_usd", 0.0),
               "model_calls": s.get("model_calls", 0), "at": _now()}
    (jd / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pdb.upsert_job(st.db_path, s["job_id"], s.get("thread_id", ""), s.get("topic", ""),
                   s.get("status", "done"), s.get("settings_snapshot", {}))
    return {"stage": "done", "status": s.get("status", "done"), "log": _log(s, "record_result: done")}


def route_after_review(s: JobState) -> str:
    return s.get("stage", "approval")


def route_after_approval(s: JobState) -> str:
    st = s.get("status", "")
    if st in ("approved", "auto-approved"):
        return "publish"
    return "wait"  # pause: awaiting-approval / approval-stale stay out of publish


def build_graph(checkpointer=None):
    g = StateGraph(JobState)
    g.add_node("discover", n_discover)
    g.add_node("choose_topic", n_choose_topic)
    g.add_node("research", n_research)
    g.add_node("fact_check", n_fact_check)
    g.add_node("script", n_script)
    g.add_node("prepare_media", n_prepare_media)
    g.add_node("render", n_render)
    g.add_node("review", n_review)
    g.add_node("approval", n_approval)
    g.add_node("publish", n_publish)
    g.add_node("record_result", n_record)
    g.set_entry_point("discover")
    g.add_edge("discover", "choose_topic")
    g.add_edge("choose_topic", "research")
    g.add_edge("research", "fact_check")
    # fact_check routes via conditional below (script | record_result when blocked)
    g.add_edge("script", "prepare_media")
    g.add_edge("prepare_media", "render")
    g.add_edge("render", "review")
    # bounded correction branch: review may send back to prepare_media (stage set by node)
    def after_review(s: JobState) -> str:
        return "prepare_media" if s.get("stage") == "prepare_media" else "approval"
    g.add_conditional_edges("review", after_review, {"prepare_media": "prepare_media", "approval": "approval"})
    g.add_conditional_edges("approval", route_after_approval, {"publish": "publish", "wait": END})
    g.add_edge("publish", "record_result")
    g.add_edge("record_result", END)
    # fact_check may jump straight to record_result when blocked (via stage) — handle:
    def after_fact(s: JobState) -> str:
        return "record_result" if s.get("stage") == "record_result" else "script"
    g.add_conditional_edges("fact_check", after_fact, {"record_result": "record_result", "script": "script"})
    return g.compile(checkpointer=checkpointer)


def initial_state(job_id: str, settings: Settings, topic: str = "") -> JobState:
    return {"job_id": job_id, "thread_id": f"thread-{job_id}",
            "settings_snapshot": settings.model_dump(), "stage": "discover", "status": "started",
            "topic": topic, "sources": [], "candidates": [], "claims": [], "cost_usd": 0.0,
            "model_calls": 0, "attempts": 0, "receipts": [], "artifacts": {}, "log": []}


def resume_job(settings: Settings, job_id: str, checkpointer=None) -> dict:
    """Restart-safe resume: reuse persisted artifacts, skip completed expensive work.
    Reads job dir JSON files; only re-runs stages whose artifacts are missing."""
    from langgraph.checkpoint.memory import MemorySaver

    jd = _job_dir(settings.job_root, job_id)
    pdb.migrate(settings.db_path)
    state: JobState = {"job_id": job_id, "thread_id": f"thread-{job_id}",
                       "settings_snapshot": settings.model_dump(), "stage": "discover",
                       "status": "resumed", "topic": "", "sources": [], "cost_usd": 0.0,
                       "model_calls": 0, "attempts": 0, "receipts": [], "artifacts": {}, "log": []}
    if (jd / "sources.json").exists():
        state["sources"] = json.loads((jd / "sources.json").read_text(encoding="utf-8"))
    if (jd / "script.json").exists():
        state["script"] = json.loads((jd / "script.json").read_text(encoding="utf-8"))
        state["scenes"] = state["script"].get("scenes", [])
        state["topic"] = state["script"].get("title", "")
    if (jd / "fact_report.json").exists():
        state["fact_report"] = json.loads((jd / "fact_report.json").read_text(encoding="utf-8"))
        state["claims"] = state["fact_report"].get("verified", [])
    if (jd / "review.json").exists():
        state["review"] = json.loads((jd / "review.json").read_text(encoding="utf-8"))
    if (jd / "approval.json").exists():
        state["approval"] = json.loads((jd / "approval.json").read_text(encoding="utf-8"))
    arts: dict = {}
    for k, f in (("audio", "narration.wav"), ("captions", "captions.srt"),
                 ("manifest", "render_manifest.json"), ("video", "documentary.mp4"),
                 ("thumbnail", "thumbnail.jpg")):
        if (jd / f).exists():
            arts[k] = str(jd / f)
    state["artifacts"] = arts
    # decide continuation point
    if arts.get("video") and state.get("approval", {}).get("approved"):
        state.update(n_publish(state))
        if state.get("stage") == "record_result":
            state.update(n_record(state))
        return state
    if arts.get("video"):
        state.update(n_approval(state))
        if state.get("status") in ("approved", "auto-approved"):
            state.update(n_publish(state))
            state.update(n_record(state))
        return state
    # otherwise full re-run is cheapest to reason about (fixture); live keeps sources
    from .checkpoints import checkpoint_cm

    if checkpointer is not None:
        app = build_graph(checkpointer)
        cfg = {"configurable": {"thread_id": f"thread-{job_id}"}}
        return app.invoke(initial_state(job_id, settings, state.get("topic", "")), config=cfg)
    with checkpoint_cm(settings.db_path + ".checkpoints.sqlite") as ckpt:
        app = build_graph(ckpt)
        cfg = {"configurable": {"thread_id": f"thread-{job_id}"}}
        return app.invoke(initial_state(job_id, settings, state.get("topic", "")), config=cfg)


def run_job(settings: Settings, topic: str = "", job_id: str | None = None,
            checkpointer=None, max_steps: int = 30) -> dict:
    """Scheduler-ready entrypoint (manual by default; NOT auto-scheduled)."""
    from .checkpoints import checkpoint_cm
    from ..providers.llm import export_keys_to_env

    pdb.migrate(settings.db_path)
    export_keys_to_env(settings)
    jid = job_id or f"job-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": f"thread-{jid}"}}
    state = initial_state(jid, settings, topic)
    if checkpointer is not None:  # explicit saver (e.g. tests with MemorySaver)
        return build_graph(checkpointer).invoke(state, config=cfg)
    with checkpoint_cm(settings.db_path + ".checkpoints.sqlite") as ckpt:
        return build_graph(ckpt).invoke(state, config=cfg)
