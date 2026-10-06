"""CLI: manual runs first; scheduler-ready entrypoint (no auto-schedule installed)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import get_settings
from .persistence import db as pdb
from .providers.llm import export_keys_to_env
from .workflow import graph as G
from .workflow.approval import approve_job
from .workflow.checkpoints import get_checkpointer


def cmd_run(args) -> None:
    st = get_settings()
    export_keys_to_env(st)
    if args.topic:
        pass
    ckpt = get_checkpointer(st.db_path)
    out = G.run_job(st, topic=args.topic or "", job_id=args.job_id, checkpointer=ckpt)
    print(json.dumps({"job_id": out.get("job_id"), "status": out.get("status"),
                      "stage": out.get("stage"), "artifacts": out.get("artifacts", {}),
                      "log": out.get("log", [])[-8:]}, ensure_ascii=False, indent=2))


def cmd_approve(args) -> None:
    st = get_settings()
    appr = approve_job(st.job_root, args.job_id, tuple(args.destinations.split(",")), by="cli-operator")
    print(json.dumps(appr, indent=2))


def cmd_resume(args) -> None:
    """Resume from persisted checkpoint without repeating completed expensive work."""
    st = get_settings()
    out = G.resume_job(st, args.job_id)
    print(json.dumps({"job_id": out.get("job_id"), "status": out.get("status"),
                      "stage": out.get("stage"), "receipts": out.get("receipts", [])},
                     ensure_ascii=False, indent=2))


def cmd_auth_youtube(args) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    from .persistence import vault as V
    from .publishing.adapters import get_adapter

    st = get_settings()
    export_keys_to_env(st)
    label = getattr(args, "account", "youtube-main")
    owner = V.current_owner(st)
    flow = InstalledAppFlow.from_client_secrets_file(
        st.youtube_client_secrets or "client_secrets.json",
        ["https://www.googleapis.com/auth/youtube.upload"])
    creds = flow.run_local_server(port=0)
    dest = V.vault_dir(st.db_path) / f"yt-{label}.token.json".replace(" ", "_")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(creds.to_json(), encoding="utf-8")
    import os as _os
    _os.chmod(dest, 0o600)
    info = get_adapter("youtube").verify({"token_file": str(dest)})
    acc = V.connect_account(st.db_path, owner, "youtube", label,
                            {"token_file": str(dest)}, info)
    print(f"Connected YouTube as {info.get('account')} (account {acc['id']}). Nothing published.")


def cmd_accounts(args) -> None:
    import json as _json

    from .persistence import vault as V

    st = get_settings()
    owner = V.current_owner(st)
    for a in V.list_accounts(st.db_path, owner):
        print(_json.dumps({k: a[k] for k in ("id", "platform", "label", "status", "public_meta")}))


def cmd_chat(args) -> None:
    """Interactive chat with the Main Deep Agent (planning/delegation harness)."""
    from .agents.main_agent import create_main_agent
    from .workflow.checkpoints import checkpoint_cm

    st = get_settings()
    export_keys_to_env(st)
    thread = args.thread or "chat-1"
    print(f"Chat with the Main Deep Agent (model={st.news_model or 'fixture'}). Type /quit to exit.")
    with checkpoint_cm(st.db_path + ".checkpoints.sqlite") as ckpt:
        agent = create_main_agent(st, checkpointer=ckpt, slim=True)
        cfg = {"configurable": {"thread_id": thread}}
        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text in ("/quit", "/exit", "quit"):
                break
            try:
                out = agent.invoke({"messages": [{"role": "user", "content": text}]}, config=cfg)
            except Exception as e:
                msg = str(e)
                if "413" in msg or "too large" in msg.lower() or "rate_limit" in msg.lower():
                    print("agent> [token limit hit on your Groq tier — wait ~1 min, keep messages short, "
                          "or upgrade at console.groq.com/settings/billing]")
                    continue
                print(f"agent> [error: {msg[:400]}]")
                continue
            msgs = out.get("messages", []) or []
            answered = False
            for m in reversed(msgs):
                if m.__class__.__name__ == "AIMessage" and getattr(m, "content", ""):
                    print(f"agent> {m.content[:4000]}")
                    answered = True
                    break
            if not answered:
                print("agent> (no text reply)")


def cmd_schedule_hint(args) -> None:
    print("Scheduler-ready (manual by default). Example cron (Asia/Dhaka daily 07:00):")
    print("0 1 * * * cd /opt/news-documentary-agent && uv run newsdoc run --topic '' >> data/cron.log 2>&1")
    print("No schedule is installed automatically.")


def app() -> None:
    p = argparse.ArgumentParser(prog="newsdoc")
    sub = p.add_subparsers(required=True)
    r = sub.add_parser("run"); r.add_argument("--topic", default=""); r.add_argument("--job-id", default=None); r.set_defaults(f=cmd_run)
    a = sub.add_parser("approve"); a.add_argument("job_id"); a.add_argument("--destinations", default="youtube"); a.set_defaults(f=cmd_approve)
    rs = sub.add_parser("resume"); rs.add_argument("job_id"); rs.set_defaults(f=cmd_resume)
    ch = sub.add_parser("chat"); ch.add_argument("--thread", default="chat-1"); ch.set_defaults(f=cmd_chat)
    au = sub.add_parser("auth-youtube"); au.add_argument("--account", default="youtube-main"); au.set_defaults(f=cmd_auth_youtube)
    la = sub.add_parser("accounts"); la.set_defaults(f=cmd_accounts)
    sc = sub.add_parser("schedule-hint"); sc.set_defaults(f=cmd_schedule_hint)
    ns = p.parse_args()
    ns.f(ns)
