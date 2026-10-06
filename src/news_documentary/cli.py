"""CLI: local runs (standalone) + shared mode (same backend API as the browser).

LOCAL (standalone, unchanged): run/chat/approve/resume/accounts operate on local
JOB_ROOT + sqlite directly. These jobs do NOT automatically appear in the browser.

SHARED (browser-interop): api-login/api-chat/api-create/api-list/api-status/
api-follow/api-resume/api-download/api-review/api-publish talk to the Express API
(API_BASE_URL, default http://localhost:4000). Terminal-created shared jobs appear
in the browser and vice versa under the same ownership + publishing rules.
"""
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


# ------------------------------------------------------- shared mode (API) ---
def _stok(args) -> str:
    from . import api_client as C

    tok = getattr(args, "token", "") or C.load_saved_token()
    if not tok:
        raise SystemExit("Missing token: run `newsdoc api-login --email E --password P` first.")
    return tok


def cmd_api_login(args) -> None:
    from . import api_client as C

    out = C._req("POST", "/api/auth/login", "", {"email": args.email, "password": args.password})
    tok = out.get("token", "")
    Path(C.token_path()).write_text(tok)
    print(f"Logged in as {out.get('user', {}).get('email')}. Token saved to {C.token_path()} (NEWSDOC_TOKEN also works).")


def cmd_api_register(args) -> None:
    from . import api_client as C

    out = C._req("POST", "/api/auth/register", "", {"email": args.email, "password": args.password})
    Path(C.token_path()).write_text(out.get("token", ""))
    print(f"Registered {args.email}. Token saved.")


def cmd_api_chat(args) -> None:
    """Shared chat: same backend threads as the browser. Documentary requests queue jobs."""
    from . import api_client as C

    tok = _stok(args)
    thread = args.thread
    if args.message:
        out = C._req("POST", f"/api/chat/threads/{thread}/messages", tok, {"content": args.message})
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print(f"Shared chat [{thread}] (same threads as browser). Type /quit to exit.")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text or text in ("/quit", "/exit", "quit"):
            break
        out = C._req("POST", f"/api/chat/threads/{thread}/messages", tok, {"content": text})
        print(f"agent> {out.get('reply', '')[:3000]}")
        if out.get("job_id"):
            print(f"(job {out['job_id']} queued — `newsdoc api-follow {out['job_id']}` to watch)")


def cmd_api_create(args) -> None:
    """Shared job creation (active scope: report | social). Video jobs are
    rejected by the API; legacy video code is preserved but disabled."""
    from . import api_client as C

    out = C._req("POST", "/api/jobs", _stok(args),
                 {"topic": args.topic, "thread_id": args.thread,
                  "settings": {"job_type": args.job_type, "language": args.lang,
                               "platforms": [p.strip() for p in
                                              (args.platforms or "x,facebook,hikmah").split(",")
                                              if p.strip()]}})
    print(json.dumps(out, indent=2))


def cmd_api_revise(args) -> None:
    """Explicit revision: stores the note, invalidates stale approval, requeues.
    The worker reuses research + fact-check and reruns write -> review."""
    from . import api_client as C

    out = C._req("POST", f"/api/jobs/{args.job_id}/revise", _stok(args),
                 {"note": args.note})
    print(json.dumps(out, indent=2))


def cmd_api_texts(args) -> None:
    """Show generated (+ edited) social texts for a job."""
    from . import api_client as C

    out = C._req("GET", f"/api/social/{args.job_id}/texts", _stok(args))
    for plat, text in (out.get("texts") or {}).items():
        gen = (out.get("generated") or {}).get(plat, {})
        print(f"===== {plat} ({len(text)} chars, claims={','.join(gen.get('claim_ids', []))}) =====")
        print(text)
        print()


def cmd_api_social_review(args) -> None:
    """Two-step explicit text publish from the terminal (mirrors browser)."""
    from . import api_client as C

    tok = _stok(args)
    cur = C._req("GET", f"/api/social/{args.job_id}/texts", tok)
    print("Current texts:", json.dumps(
        {k: (v[:120] + "…") for k, v in (cur.get("texts") or {}).items()},
        ensure_ascii=False)[:800])
    sels = [{"account_id": a} for a in args.accounts.split(",") if a.strip()]
    review = C._req("POST", f"/api/social/{args.job_id}/review", tok,
                    {"texts": cur.get("texts") or {},
                     "selections": sels} if not args.text_file else
                    {"texts": json.loads(Path(args.text_file).read_text(encoding="utf-8")),
                     "selections": sels})
    print("TEXT REVIEW BOUND:")
    print(json.dumps({k: review.get(k) for k in ("content_hash", "selections")}, indent=2))
    if args.publish:
        if input(f"Type PUBLISH to post {args.job_id} texts to {[s['account_id'] for s in sels]}: ").strip() != "PUBLISH":
            print("Aborted (nothing published).")
            return
        print(json.dumps(C._req("POST", f"/api/social/{args.job_id}/publish", tok, {}), indent=2))
    else:
        print("Review recorded. Re-run with --publish to explicitly publish (agent cannot do this).")


def cmd_doc_run(args) -> None:
    """Standalone local doc run (report|social). Does NOT appear in the browser;
    use api-create for shared jobs."""
    from .config import get_settings as _gs
    from .workflow import doc_graph as D

    st = _gs()
    st.job_type = args.job_type
    st.narration_lang = args.lang
    out = D.run_doc_job(st, topic=args.topic, job_type=args.job_type, job_id=args.job_id)
    print(json.dumps({"job_id": out.get("job_id"), "status": out.get("status"),
                      "stage": out.get("stage"), "artifacts": out.get("artifacts", {}),
                      "log": out.get("log", [])[-8:]}, ensure_ascii=False, indent=2))


def cmd_api_list(args) -> None:
    from . import api_client as C

    jobs = C._req("GET", "/api/jobs", _stok(args))
    for j in jobs if isinstance(jobs, list) else []:
        print(f"{j['job_id']}  {j['status']}/{j['stage']}  {j.get('topic','')[:80]}")


def cmd_api_status(args) -> None:
    from . import api_client as C

    print(json.dumps(C._req("GET", f"/api/jobs/{args.job_id}", _stok(args)), indent=2))
    print("--- events ---")
    print(json.dumps(C._req("GET", f"/api/jobs/{args.job_id}/job-events", _stok(args)), indent=2)[:3000])


def cmd_api_follow(args) -> None:
    """Follow live progress (HTTP polling; reconnect recovers persisted status)."""
    from . import api_client as C

    import time

    tok, after, seen = _stok(args), 0, set()
    while True:
        evs = C._req("GET", f"/api/jobs/{args.job_id}/job-events?after={after}", tok)
        for e in evs if isinstance(evs, list) else []:
            if e.get("id") not in seen:
                print(f"[{e.get('kind')}] {e.get('message','')[:200]}")
                seen.add(e.get("id"))
                after = max(after, e.get("id", after))
        st = C._req("GET", f"/api/jobs/{args.job_id}", tok)
        if isinstance(st, dict) and str(st.get("status")) in (
                "published", "failed", "cancelled", "done", "awaiting-approval", "blocked-no-evidence"):
            print(f"FINAL: {st.get('status')} @ {st.get('stage')}")
            break
        time.sleep(3)


def cmd_api_resume(args) -> None:
    from . import api_client as C

    print(json.dumps(C._req("POST", f"/api/jobs/{args.job_id}/resume", _stok(args), {}), indent=2))


def cmd_api_download(args) -> None:
    from . import api_client as C

    import urllib.request

    tok = _stok(args)
    base = C._base()
    dest = Path(args.dest or f"{args.job_id}_{args.name}")
    req = urllib.request.Request(f"{base}/api/jobs/{args.job_id}/artifacts/{args.name}",
                                 headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    print(f"Saved {dest} ({dest.stat().st_size} bytes).")


def cmd_api_review(args) -> None:
    """Two-step explicit publish from the terminal (mirrors browser Review & Publish)."""
    from . import api_client as C

    tok = _stok(args)
    meta = C._req("GET", f"/api/publish/{args.job_id}/meta", tok)
    print("Current title/description:", json.dumps(meta, ensure_ascii=False)[:500])
    sels = [{"account_id": a, "visibility": args.visibility} for a in args.accounts.split(",") if a.strip()]
    review = C._req("POST", f"/api/publish/{args.job_id}/review", tok,
                    {"title": args.title or meta.get("title", ""),
                     "description": args.description or meta.get("description", ""),
                     "selections": sels})
    print("REVIEW BOUND:")
    print(json.dumps({k: review.get(k) for k in ("video_hash", "metadata_hash", "title", "selections")}, indent=2))
    if args.publish:
        if input(f"Type PUBLISH to upload {args.job_id} to {[s['account_id'] for s in sels]}: ").strip() != "PUBLISH":
            print("Aborted (nothing published).")
            return
        print(json.dumps(C._req("POST", f"/api/publish/{args.job_id}/publish", tok, {}), indent=2))
    else:
        print("Review recorded. Re-run with --publish to explicitly publish (agent cannot do this).")


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
    # --- shared mode (same backend as browser) ---
    rl = sub.add_parser("api-register"); rl.add_argument("--email", required=True); rl.add_argument("--password", required=True); rl.set_defaults(f=cmd_api_register)
    li = sub.add_parser("api-login"); li.add_argument("--email", required=True); li.add_argument("--password", required=True); li.set_defaults(f=cmd_api_login)
    ch2 = sub.add_parser("api-chat"); ch2.add_argument("--thread", default="chat-1"); ch2.add_argument("--message", default=""); ch2.add_argument("--token", default=""); ch2.set_defaults(f=cmd_api_chat)
    cr = sub.add_parser("api-create"); cr.add_argument("--topic", required=True); cr.add_argument("--thread", default=None); cr.add_argument("--job-type", default="report", choices=["report", "social"]); cr.add_argument("--lang", default="en"); cr.add_argument("--platforms", default="x,facebook,hikmah"); cr.add_argument("--token", default=""); cr.set_defaults(f=cmd_api_create)
    rv2 = sub.add_parser("api-revise"); rv2.add_argument("job_id"); rv2.add_argument("--note", required=True); rv2.add_argument("--token", default=""); rv2.set_defaults(f=cmd_api_revise)
    tx = sub.add_parser("api-texts"); tx.add_argument("job_id"); tx.add_argument("--token", default=""); tx.set_defaults(f=cmd_api_texts)
    sr = sub.add_parser("api-social-review"); sr.add_argument("job_id"); sr.add_argument("--accounts", default="", help="comma-separated account ids"); sr.add_argument("--text-file", default="", help="optional JSON file with edited texts"); sr.add_argument("--publish", action="store_true"); sr.add_argument("--token", default=""); sr.set_defaults(f=cmd_api_social_review)
    dr = sub.add_parser("run-doc"); dr.add_argument("--topic", default=""); dr.add_argument("--job-type", default="report", choices=["report", "social"]); dr.add_argument("--lang", default="en"); dr.add_argument("--job-id", default=None); dr.set_defaults(f=cmd_doc_run)
    lj = sub.add_parser("api-list"); lj.add_argument("--token", default=""); lj.set_defaults(f=cmd_api_list)
    st2 = sub.add_parser("api-status"); st2.add_argument("job_id"); st2.add_argument("--token", default=""); st2.set_defaults(f=cmd_api_status)
    fo = sub.add_parser("api-follow"); fo.add_argument("job_id"); fo.add_argument("--token", default=""); fo.set_defaults(f=cmd_api_follow)
    rs2 = sub.add_parser("api-resume"); rs2.add_argument("job_id"); rs2.add_argument("--token", default=""); rs2.set_defaults(f=cmd_api_resume)
    dl = sub.add_parser("api-download"); dl.add_argument("job_id"); dl.add_argument("name", help="artifact file, e.g. report.pdf, posts.json, documentary.mp4 (legacy)"); dl.add_argument("--dest", default=""); dl.add_argument("--token", default=""); dl.set_defaults(f=cmd_api_download)
    rv = sub.add_parser("api-review", help="legacy video review (preserved; video scope disabled)"); rv.add_argument("job_id"); rv.add_argument("--accounts", default="", help="comma-separated account ids"); rv.add_argument("--visibility", default="unlisted"); rv.add_argument("--title", default=""); rv.add_argument("--description", default=""); rv.add_argument("--publish", action="store_true"); rv.add_argument("--token", default=""); rv.set_defaults(f=cmd_api_review)
    ns = p.parse_args()
    ns.f(ns)
