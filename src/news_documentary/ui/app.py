"""Operator UI: discover, settings, run, stages/costs, evidence/script, video, revise, approve/publish, resume."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from news_documentary.config import get_settings
from news_documentary.workflow import graph as G
from news_documentary.workflow.approval import approve_job
from news_documentary.workflow.checkpoints import get_checkpointer


st.set_page_config(page_title="News Documentary Operator", layout="wide")
st.title("News Documentary — Operator Console")

settings = get_settings()
with st.sidebar:
    st.header("Settings")
    topic = st.text_input("Topic (blank = discover)", "")
    aspect = st.selectbox("Aspect", ["vertical", "horizontal"],
                          index=0 if settings.video_aspect == "vertical" else 1)
    policy = st.selectbox("Publish policy", ["manual", "auto"],
                          index=0 if settings.publish_policy == "manual" else 1)
    lang = st.text_input("Narration lang", settings.narration_lang)
    st.caption(f"TTS={settings.tts_provider} · Model={'fixture' if not settings.news_model else settings.news_model}")

if st.button("Run job"):
    settings.video_aspect = aspect
    settings.publish_policy = policy
    settings.narration_lang = lang
    out = G.run_job(settings, topic=topic)
    st.session_state["job_id"] = out.get("job_id")
    st.session_state["out"] = out

job_id = st.session_state.get("job_id", "")
if job_id:
    jd = Path(settings.job_root) / job_id
    out = st.session_state.get("out", {})
    st.subheader(f"Job {job_id} — {out.get('status','')} @ {out.get('stage','')}")
    st.write("Cost (est):", out.get("cost_usd", 0.0), "| model calls:", out.get("model_calls", 0))
    for line in (out.get("log", []) or [])[-15:]:
        st.text(line)
    for name in ["research_notes.json", "fact_report.json", "script.json", "review.json", "result.json"]:
        p = jd / name
        if p.exists():
            with st.expander(name):
                st.code(p.read_text(encoding="utf-8")[:6000])
    v = jd / "documentary.mp4"
    if v.exists():
        st.video(str(v))
    c1, c2, c3 = st.columns(3)
    if c1.button("Approve + publish (YouTube)"):
        approve_job(settings.job_root, job_id, ("youtube",), by="ui-operator")
        res = G.resume_job(settings, job_id)
        st.session_state["out"] = res
        st.success(f"Published: {res.get('receipts')}")
        st.rerun()
    if c2.button("Resume"):
        res = G.resume_job(settings, job_id)
        st.session_state["out"] = res
        st.rerun()
    if c3.button("Request revision (back to media prep)"):
        ckpt = get_checkpointer(settings.db_path)
        app = G.build_graph(ckpt)
        cfg = {"configurable": {"thread_id": f"thread-{job_id}"}}
        snap = app.get_state(cfg)
        vals = dict(snap.values or {})
        vals["stage"] = "prepare_media"
        res = app.invoke(vals, config=cfg)
        st.session_state["out"] = res
        st.rerun()
else:
    st.info("Run a job to inspect evidence, script, video, and approval.")
