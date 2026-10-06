"""Operator UI: Generate (no account needed) / Review & Publish / Connected Accounts."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from news_documentary.config import get_settings
from news_documentary.media.bundle import build_manual_bundle
from news_documentary.persistence import vault as V
from news_documentary.publishing import service as pub
from news_documentary.publishing.adapters import ADAPTERS
from news_documentary.workflow import graph as G
from news_documentary.workflow.approval import approve_job

st.set_page_config(page_title="News Documentary Operator", layout="wide")

settings = get_settings()
if "owner" not in st.session_state:
    st.session_state["owner"] = V.current_owner(settings)
owner = st.sidebar.text_input("Owner (connections/jobs are scoped to this ID)",
                              st.session_state["owner"])
st.session_state["owner"] = owner
page = st.sidebar.radio("Page", ["Generate", "Review & Publish", "Connected Accounts"])

st.title("News Documentary — Operator Console")
st.caption(f"Owner: {owner} · Model: {settings.news_model or 'fixture'} · "
           f"TTS: {settings.tts_provider} · Lang: {settings.narration_lang}")


def job_ids_with_video() -> list[str]:
    root = Path(settings.job_root)
    if not root.exists():
        return []
    return sorted((p.name for p in root.iterdir()
                   if (p / "documentary.mp4").exists()),
                  key=lambda j: (root / j / "documentary.mp4").stat().st_mtime, reverse=True)


# ------------------------------------------------------------- Generate ---
if page == "Generate":
    st.header("Generate documentary (no social account needed)")
    topic = st.text_input("Topic (blank = auto-discover)", "")
    c1, c2, c3 = st.columns(3)
    aspect = c1.selectbox("Aspect", ["vertical", "horizontal"],
                          index=0 if settings.video_aspect == "vertical" else 1)
    lang = c2.text_input("Narration language", settings.narration_lang)
    policy = c3.selectbox("Publish policy", ["manual", "auto"],
                          index=0 if settings.publish_policy == "manual" else 1)
    if st.button("Run job", type="primary"):
        settings.video_aspect = aspect
        settings.publish_policy = policy
        settings.narration_lang = lang
        with st.spinner("Researching, verifying, rendering…"):
            out = G.run_job(settings, topic=topic)
        st.session_state["last_job"] = out.get("job_id")
        st.success(f"Job {out.get('job_id')}: {out.get('status')} @ {out.get('stage')}")
        for line in (out.get("log", []) or [])[-12:]:
            st.text(line)
    jid = st.session_state.get("last_job", "")
    if jid and (Path(settings.job_root) / jid / "documentary.mp4").exists():
        st.video(str(Path(settings.job_root) / jid / "documentary.mp4"))
        st.info("Next: open 'Review & Publish' to preview, download, or publish this video.")

# ------------------------------------------------------- Review & Publish ---
elif page == "Review & Publish":
    st.header("Review, download, publish")
    jobs = job_ids_with_video()
    if not jobs:
        st.info("No rendered videos yet — generate one first.")
        st.stop()
    jid = st.selectbox("Job", jobs)
    jd = Path(settings.job_root) / jid
    st.video(str(jd / "documentary.mp4"))

    meta = pub.default_meta(settings.job_root, jid)
    title = st.text_input("Title", meta.get("title", jid))
    desc = st.text_area("Description", meta.get("description", ""), height=120)
    if st.button("Save title/description (draft — not yet authorized)"):
        pub.save_meta(settings.job_root, owner, jid, title, desc)
        st.success("Draft saved. Review & authorize below to bind it for publishing.")

    st.subheader("Manual path (no account needed)")
    try:
        bundle = build_manual_bundle(settings.job_root, jid, title, desc)
        cols = st.columns(len(bundle))
        for (name, path), col in zip(bundle.items(), cols):
            col.download_button(f"Download {name}", data=Path(path).read_bytes(),
                                file_name=f"{jid}_{name}{Path(path).suffix}")
    except FileNotFoundError as e:
        st.error(str(e))

    st.subheader("Connected path")
    accs = [a for a in V.list_accounts(settings.db_path, owner) if a["status"] == "connected"]
    if not accs:
        st.warning("No connected accounts. Connect one on the 'Connected Accounts' page first.")
    else:
        sels, viss = [], {}
        for a in accs:
            on = st.checkbox(f"{ADAPTERS[a['platform']].display} — {a['label']}", key=f"sel_{a['id']}")
            viss[a["id"]] = st.selectbox(f"Visibility ({a['label']})",
                                         ["public", "unlisted", "private"], index=0, key=f"vis_{a['id']}")
            if on:
                sels.append({"account_id": a["id"], "platform": a["platform"],
                             "visibility": viss[a["id"]]})
        review = json.loads((jd / "publish_review.json").read_text()) if (jd / "publish_review.json").exists() else None
        if review:
            st.code(json.dumps({"video_hash": review["video_hash"][:16] + "…",
                                "metadata_hash": review["metadata_hash"][:16] + "…",
                                "title": review["title"],
                                "destinations": [(s["platform"], s["label"], s["visibility"])
                                                 for s in review["selections"]]}, indent=2))
        if st.button("Review & authorize this version", type="primary"):
            try:
                pub.save_meta(settings.job_root, owner, jid, title, desc)
                r = pub.build_review(settings.db_path, owner, settings.job_root, jid, sels)
                st.success(f"Authorized {len(r['selections'])} destination(s). "
                           "Any later change needs a new review.")
                st.rerun()
            except Exception as e:
                st.error(str(e)[:500])
        if st.button("Publish reviewed version"):
            try:
                with st.spinner("Uploading per destination…"):
                    results = pub.publish_reviewed(settings.db_path, owner, settings.job_root, jid)
                for r in results:
                    label = f"{r.get('platform')} ({r.get('account_id', '')[:18]})"
                    if str(r.get("status", "")).startswith("succeeded"):
                        st.success(f"{label}: {r.get('status')} → {r.get('url') or r.get('remote_id')}")
                    elif r.get("skipped"):
                        st.info(f"{label}: skipped ({r.get('reason')})")
                    else:
                        st.error(f"{label}: {r.get('status')} — {r.get('note', '')[:300]}")
            except Exception as e:
                st.error(str(e)[:500])
        if st.button("Retry failed destinations only"):
            try:
                results = pub.retry_failed(settings.db_path, owner, settings.job_root, jid)
                st.json([{k: r.get(k) for k in ("platform", "status", "url", "remote_id", "note", "reason")
                          if r.get(k)} for r in results])
            except Exception as e:
                st.error(str(e)[:500])

# ---------------------------------------------------------------- Accounts ---
else:
    st.header("Connected accounts")
    st.caption("Connecting stores credentials server-side only. It NEVER publishes anything. "
               "Tokens are never shown, logged, or sent to the AI.")
    for a in V.list_accounts(settings.db_path, owner):
        disp = ADAPTERS[a["platform"]].display if a["platform"] in ADAPTERS else a["platform"]
        with st.expander(f"{disp} — {a['label']} [{a['status']}]"):
            st.write("Public info:", a["public_meta"])
            if a["status"] == "connected" and st.button("Disconnect", key=f"dis_{a['id']}"):
                V.disconnect_account(settings.db_path, owner, a["id"])
                st.success("Disconnected. The stored secret was deleted; it cannot publish.")
                st.rerun()
    st.subheader("Connect a new account")
    plat = st.selectbox("Platform", ["youtube", "facebook", "x", "hikmah"])
    st.info(ADAPTERS[plat].setup_help)
    label = st.text_input("Account label", f"my-{plat}")
    secret: dict = {}
    public_meta: dict = {}
    ok = False
    if plat == "youtube":
        st.write("Run this once on the server, then upload the token file here:")
        st.code(f"uv run newsdoc auth-youtube --account {label or 'LABEL'}", language="bash")
        tok = st.file_uploader("youtube_token.json", type=["json"])
        if tok and st.button("Verify & connect YouTube"):
            data_dir = Path(settings.db_path).parent / "tokens"
            data_dir.mkdir(parents=True, exist_ok=True)
            tmp = data_dir / f"pending_{label}.json"
            tmp.write_bytes(tok.read())
            secret, ok = {"token_file": str(tmp)}, True
    elif plat == "facebook":
        page_id = st.text_input("Page ID")
        page_token = st.text_input("Page access token", type="password")
        if page_token and st.button("Verify & connect Facebook"):
            secret, public_meta = {"page_id": page_id, "page_token": page_token}, {}
            ok = True
    elif plat == "x":
        x_tok = st.text_input("X user access token", type="password")
        x_ref = st.text_input("X refresh token (optional)", type="password")
        if x_tok and st.button("Verify & connect X"):
            secret = {"access_token": x_tok, "refresh_token": x_ref}
            ok = True
    elif plat == "hikmah":
        base = st.text_input("Hikmah base URL", "https://hikmah.net")
        h_tok = st.text_input("Hikmah API token", type="password")
        if h_tok and st.button("Verify & connect Hikmah"):
            secret = {"base_url": base.rstrip("/"), "token": h_tok}
            ok = True
    if ok:
        try:
            info = ADAPTERS[plat].verify(secret)
            acc = V.connect_account(settings.db_path, owner, plat, label, secret, info)
            if plat == "youtube":  # move pending token file to its final vault name
                import shutil

                dest = V.vault_dir(settings.db_path) / f"{acc['id']}.token.json"
                shutil.move(secret["token_file"], dest)
                V.store_secret(settings.db_path, acc["id"], {"token_file": str(dest)})
            st.success(f"Connected {plat} as {info.get('account')}. Nothing was published.")
            st.rerun()
        except Exception as e:
            st.error(f"Connect failed (nothing stored): {str(e)[:400]}")
