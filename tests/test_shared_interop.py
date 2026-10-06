"""Shared-mode interop tests: Express API + Python worker bridge (offline).

Spawns the real Express API on an ephemeral port with a temp sqlite DB and
exercises browser/terminal interoperability: same jobs, progress, artifacts,
ownership isolation, review-bound publishing, duplicate prevention.
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _http(base: str, method: str, path: str, token: str = "", payload: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode() if payload is not None else None,
        method=method, headers={"Content-Type": "application/json",
                                **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return r.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("shared")
    port = _free_port()
    env = {**os.environ,
           "JWT_SECRET": "test-secret", "WORKER_SERVICE_TOKEN": "test-worker",
           "ACCOUNTS_ENCRYPTION_KEY": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
           "API_PORT": str(port), "DB_PATH": str(tmp / "t.sqlite"),
           "JOB_ROOT": str(tmp / "jobs")}
    proc = subprocess.Popen(["npx", "tsx", "src/index.ts"], cwd=str(API_DIR), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://localhost:{port}"
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=5) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(1)
    else:
        out = proc.stdout.read().decode() if proc.stdout else ""
        proc.kill()
        raise RuntimeError(f"API did not boot: {out[-2000:]}")
    yield {"base": base, "env": env, "tmp": tmp, "proc": proc}
    proc.kill()


def _register(base: str, email: str) -> str:
    code, body = _http(base, "POST", "/api/auth/register", "", {"email": email, "password": "password123"})
    assert code == 200, body
    return body["token"]


def test_terminal_browser_job_interop(api):
    base = api["base"]
    alice = _register(base, "alice@test.com")
    bob = _register(base, "bob@test.com")
    # terminal-created shared job ...
    code, job = _http(base, "POST", "/api/jobs", alice,
                      {"topic": "Interop probe", "settings": {"topic": "Interop probe"}})
    assert code == 201, job
    jid = job["job_id"]
    # ... appears in the browser (same owner, same API) ...
    code, jobs = _http(base, "GET", "/api/jobs", alice)
    assert code == 200 and any(j["job_id"] == jid for j in jobs)
    # ... but never leaks to another user.
    code, _ = _http(base, "GET", f"/api/jobs/{jid}", bob)
    assert code == 404
    # chat documentary request queues a shared job on the same backend
    code, out = _http(base, "POST", "/api/chat/threads/chat-1/messages", alice,
                      {"content": "create a documentary about interop probes"})
    assert code == 200 and out["job_id"]
    # worker lease via internal queue (service token, not user token).
    # direct internal call needs the service token header:
    req = urllib.request.Request(
        base + "/api/jobs/internal/next", data=json.dumps({"worker_id": "w1"}).encode(),
        method="POST", headers={"Content-Type": "application/json", "X-Service-Token": "test-worker"})
    with urllib.request.urlopen(req, timeout=30) as r:
        nxt = json.loads(r.read().decode())
    assert nxt["job"]["job_id"] in (jid, out["job_id"])
    # progress posted by the worker is visible to the owner (polling/SSE recovery)
    req = urllib.request.Request(
        base + f"/api/jobs/internal/{jid}/progress",
        data=json.dumps({"kind": "research-started", "message": "Research started",
                         "stage": "research", "status": "running"}).encode(),
        method="POST", headers={"Content-Type": "application/json", "X-Service-Token": "test-worker"})
    urllib.request.urlopen(req, timeout=30).read()
    code, evs = _http(base, "GET", f"/api/jobs/{jid}/job-events", alice)
    assert code == 200 and any(e["kind"] == "research-started" for e in evs)
    # duplicate lease: a second worker cannot steal an active lease
    req = urllib.request.Request(
        base + f"/api/jobs/internal/{jid}/heartbeat",
        data=json.dumps({"worker_id": "thief"}).encode(),
        method="POST", headers={"Content-Type": "application/json", "X-Service-Token": "test-worker"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        stolen = True
    except Exception:
        stolen = False
    assert stolen is False


def test_publish_binding_and_duplicates(api):
    import hashlib

    base, tmp = api["base"], api["tmp"]
    alice = _register(base, "alice2@test.com")
    code, job = _http(base, "POST", "/api/jobs", alice,
                      {"topic": "Publish probe", "settings": {"topic": "Publish probe"}})
    jid = job["job_id"]
    jd = Path(api["env"]["JOB_ROOT"]) / jid
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "documentary.mp4").write_bytes(b"fake-video-bytes")
    (jd / "script.json").write_text(json.dumps({"title": "T", "version": 1}))
    (jd / "sources.json").write_text("[]")
    # publish without review is blocked
    code, body = _http(base, "POST", f"/api/publish/{jid}/publish", alice, {})
    assert code in (422, 500) and "review" in str(body).lower()
    # connect (fixture) then review & publish
    code, acc = _http(base, "POST", "/api/accounts/connect", alice,
                      {"platform": "fixture", "label": "t", "secret": {}})
    assert code == 201, acc
    code, review = _http(base, "POST", f"/api/publish/{jid}/review", alice,
                         {"title": "T", "description": "D",
                          "selections": [{"account_id": acc["id"], "visibility": "public"}]})
    assert code == 200, review
    code, res1 = _http(base, "POST", f"/api/publish/{jid}/publish", alice, {})
    assert code == 200 and str(res1[0]["status"]).startswith("succeeded")
    assert res1[0]["fixture"] is True  # labeled test double, never a real upload
    # duplicate upload is skipped, never repeated
    code, res2 = _http(base, "POST", f"/api/publish/{jid}/publish", alice, {})
    assert res2[0].get("skipped") is True
    # tampering after review invalidates the binding
    (jd / "documentary.mp4").write_bytes(b"tampered!")
    code, body = _http(base, "POST", f"/api/publish/{jid}/publish", alice, {})
    assert code == 422 and "changed after review" in str(body)


def test_secrets_encrypted_and_owner_scoped(api):
    base = api["base"]
    alice = _register(base, "alice3@test.com")
    bob = _register(base, "bob3@test.com")
    code, acc = _http(base, "POST", "/api/accounts/connect", alice,
                      {"platform": "fixture", "label": "x1",
                       "secret": {"access_token": "SECRET-ABCDEFGH"}})
    assert code == 201, acc
    # cipher text at rest, never the raw secret
    c = sqlite3.connect(api["env"]["DB_PATH"])
    blob = c.execute("SELECT ciphertext FROM account_secrets WHERE account_id=?",
                     (acc["id"],)).fetchone()[0]
    c.close()
    assert "SECRET-ABCDEFGH" not in blob
    # bob cannot see or use alice's account
    code, lst = _http(base, "GET", "/api/accounts", bob)
    assert all(a["id"] != acc["id"] for a in lst)
    c = sqlite3.connect(api["env"]["DB_PATH"])
    c.execute("UPDATE account_secrets SET ciphertext=? WHERE account_id=?", (blob, acc["id"]))
    c.close()


def test_worker_runs_shared_job_end_to_end(api):
    """Python worker executes a leased API job (doc scope: research -> write ->
    review -> awaiting-approval), posting readable progress + artifact refs
    (no blobs in queue payloads)."""
    base = api["base"]
    alice = _register(base, "worker@test.com")
    code, job = _http(base, "POST", "/api/jobs", alice,
                      {"topic": "Worker e2e probe",
                       "settings": {"topic": "Worker e2e probe", "job_type": "report"}})
    jid = job["job_id"]
    env = {**os.environ, "API_BASE_URL": base, "WORKER_SERVICE_TOKEN": "test-worker",
           "JOB_ROOT": api["env"]["JOB_ROOT"], "DB_PATH": api["env"]["DB_PATH"],
           "NEWS_MODEL": "", "TAVILY_API_KEY": ""}
    # force fixture search (no network): point worker at fixture via env is automatic
    # when Tavily/RSS fail; RSS may succeed — either way the run must finish.
    for _ in range(5):  # module-scoped API may hold older queued jobs; drain in order
        r = subprocess.run(["uv", "run", "python", "-m", "news_documentary.service_worker", "--once"],
                           cwd=str(Path(__file__).resolve().parents[1]), env=env,
                           capture_output=True, text=True, timeout=600)
        assert "claimed" in (r.stdout + r.stderr), r.stdout[-2000:] + r.stderr[-2000:]
        code, j = _http(base, "GET", f"/api/jobs/{jid}", alice)
        if j["status"] != "queued":
            break
    assert j["status"] in ("awaiting-approval", "blocked-no-evidence", "reviewed-failed"), j
    code, evs = _http(base, "GET", f"/api/jobs/{jid}/job-events", alice)
    kinds = {e["kind"] for e in evs}
    assert "research-started" in kinds and "job-finished" in kinds
    assert not any("ToolCallRequest" in str(e) for e in evs)  # no raw internals in UI events
    assert "rendering-video" not in kinds and "generating-narration" not in kinds  # doc scope: no media stage
    if j["status"] == "awaiting-approval":
        code, arts = _http(base, "GET", f"/api/jobs/{jid}/artifacts", alice)
        names = {a["name"] for a in arts}
        assert "report.pdf" in names and "posts.json" in names


def test_video_stream_ranges_vtt_and_auth(api):
    """Preview streaming: authorized URLs, 206 byte-ranges for seeking,
    generated WebVTT (SRT stays the downloadable source of truth)."""
    import urllib.error
    import urllib.parse

    base = api["base"]
    alice = _register(base, "stream@test.com")
    code, job = _http(base, "POST", "/api/jobs", alice,
                      {"topic": "Stream probe", "settings": {"topic": "Stream probe"}})
    jid = job["job_id"]
    jd = Path(api["env"]["JOB_ROOT"]) / jid
    jd.mkdir(parents=True, exist_ok=True)
    payload = bytes(range(256)) * 4  # 1024 deterministic bytes
    (jd / "documentary.mp4").write_bytes(payload)
    (jd / "script.json").write_text(json.dumps({"title": "T", "version": 1}))
    (jd / "captions.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nHello world\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nSecond line\n")

    def get(path: str, token: str = "", headers: dict | None = None):
        req = urllib.request.Request(base + path, headers=dict(headers or {}))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers.items()), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers.items()), e.read()

    mp4 = f"/api/jobs/{jid}/artifacts/documentary.mp4"
    vtt = f"/api/jobs/{jid}/captions.vtt"
    srt = f"/api/jobs/{jid}/artifacts/captions.srt"

    # no token anywhere -> 401 (neither header nor query)
    assert get(mp4)[0] == 401
    assert get(vtt)[0] == 401
    # full stream via query token (what <video>/<track> use)
    tok = urllib.parse.quote(alice, safe="")
    s, h, b = get(f"{mp4}?token={tok}")
    assert s == 200 and b == payload
    assert h.get("Accept-Ranges") == "bytes"
    # first 100 bytes -> 206, exact slice (seek without full download)
    s, h, b = get(f"{mp4}?token={tok}", headers={"Range": "bytes=0-99"})
    assert s == 206 and b == payload[:100] and len(b) == 100
    assert h.get("Content-Range") == f"bytes 0-99/{len(payload)}"
    # open-ended tail
    s, h, b = get(f"{mp4}?token={tok}", headers={"Range": "bytes=1000-"})
    assert s == 206 and b == payload[1000:]
    assert h.get("Content-Range") == f"bytes 1000-1023/{len(payload)}"
    # suffix range: last 10 bytes
    s, h, b = get(f"{mp4}?token={tok}", headers={"Range": "bytes=-10"})
    assert s == 206 and b == payload[-10:]
    # unsatisfiable -> 416 with total hint
    s, h, b = get(f"{mp4}?token={tok}", headers={"Range": "bytes=5000-6000"})
    assert s == 416 and h.get("Content-Range") == f"bytes */{len(payload)}"
    # header-token auth works too (fetch-based downloads)
    req = urllib.request.Request(base + mp4, headers={"Authorization": f"Bearer {alice}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.status == 200 and r.read() == payload
    # generated WebVTT for browser playback
    s, h, b = get(f"{vtt}?token={tok}")
    text = b.decode("utf-8")
    assert s == 200 and "text/vtt" in h.get("Content-Type", "")
    assert text.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:02.500" in text and "Hello world" in text
    assert "00:00:01,000" not in text  # commas converted to VTT periods
    # VTT without captions yet -> 404, not a crash
    code, job2 = _http(base, "POST", "/api/jobs", alice,
                       {"topic": "No subs", "settings": {"topic": "No subs"}})
    assert get(f"/api/jobs/{job2['job_id']}/captions.vtt?token={tok}")[0] == 404
    # downloadable SRT stays byte-identical (source of truth)
    s, h, b = get(f"{srt}?token={tok}")
    assert s == 200 and "00:00:01,000 --> 00:00:02,500" in b.decode("utf-8")
    # another owner gets 404 (no existence leak)
    bob = _register(base, "stream-bob@test.com")
    assert get(f"{mp4}?token={urllib.parse.quote(bob, safe='')}")[0] == 404


def test_social_text_publish_binding_and_duplicates(api):
    """Connected text publishing: review-bound, duplicates skipped, tampering
    blocked, YouTube refused (no text-post API) instead of video reuse."""
    base = api["base"]
    alice = _register(base, "social@test.com")
    code, job = _http(base, "POST", "/api/jobs", alice,
                      {"topic": "Social probe",
                       "settings": {"topic": "Social probe", "job_type": "social"}})
    assert code == 201 and job["job_type"] == "social", job
    jid = job["job_id"]
    # video job_type is rejected in the active scope
    code, body = _http(base, "POST", "/api/jobs", alice,
                       {"topic": "Video probe", "settings": {"topic": "Video probe", "job_type": "video"}})
    assert code == 400 and "report | social" in str(body)
    jd = Path(api["env"]["JOB_ROOT"]) / jid
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "posts.json").write_text(json.dumps({
        "x": {"text": "Metro opens Monday.", "claim_ids": ["C1"]},
        "youtube": {"text": "Title", "claim_ids": ["C1"]}}))
    # publish without review is blocked
    code, body = _http(base, "POST", f"/api/social/{jid}/publish", alice, {})
    assert code in (422, 500) and "review" in str(body).lower()
    # connect fixture, review, publish
    code, acc = _http(base, "POST", "/api/accounts/connect", alice,
                      {"platform": "fixture", "label": "t", "secret": {}})
    assert code == 201, acc
    code, texts = _http(base, "GET", f"/api/social/{jid}/texts", alice)
    assert code == 200 and texts["texts"]["x"] == "Metro opens Monday."
    # user edits are saved as draft (not yet authorized)
    code, saved = _http(base, "PUT", f"/api/social/{jid}/texts", alice,
                        {"texts": {"x": "Metro opens Monday! edited"}})
    assert saved["texts"]["x"].endswith("edited")
    code, review = _http(base, "POST", f"/api/social/{jid}/review", alice,
                         {"selections": [{"account_id": acc["id"]}]})
    assert code == 200 and len(review["content_hash"]) == 64, review
    code, res1 = _http(base, "POST", f"/api/social/{jid}/publish", alice, {})
    assert code == 200 and str(res1[0]["status"]).startswith("succeeded")
    assert res1[0]["fixture"] is True  # labeled test double, never a real post
    # duplicate skipped, never re-posted
    code, res2 = _http(base, "POST", f"/api/social/{jid}/publish", alice, {})
    assert res2[0].get("skipped") is True
    # editing after review invalidates the binding
    code, _ = _http(base, "PUT", f"/api/social/{jid}/texts", alice,
                    {"texts": {"x": "Tampered text"}})
    assert code == 200
    code, body = _http(base, "POST", f"/api/social/{jid}/publish", alice, {})
    assert code == 422 and "authorize again" in str(body)
    # YouTube: no text-post endpoint -> refused with explanation, never video upload
    import sqlite3 as _sq

    c = _sq.connect(api["env"]["DB_PATH"])
    owner = c.execute("SELECT owner FROM accounts WHERE id=?", (acc["id"],)).fetchone()[0]
    yt = f"youtube-{jid[:8]}"
    now = "2026-10-06T00:00:00Z"
    c.execute("INSERT INTO accounts(id,owner,platform,label,status,public_meta,created_at,updated_at)"
              " VALUES(?,?,?,?,?,?,?,?)",
              (yt, owner, "youtube", "yt", "connected", '{"account":"yt"}', now, now))
    c.execute("INSERT INTO account_secrets(account_id,ciphertext,updated_at) VALUES(?,?,?)",
              (yt, c.execute("SELECT ciphertext FROM account_secrets WHERE account_id=?",
                             (acc["id"],)).fetchone()[0], now))
    c.commit()
    c.close()
    code, body = _http(base, "POST", f"/api/social/{jid}/review", alice,
                       {"selections": [{"account_id": yt}]})
    assert code == 422 and "no text" in str(body).lower()


def test_veo_unconfigured_and_storage_refs(tmp_path):
    from news_documentary.providers.veo import UnconfiguredVeo, veo_enabled

    assert veo_enabled(None) is False
    with pytest.raises(UnconfiguredVeo):
        from news_documentary.providers.veo import generate_scene_clip

        generate_scene_clip("test", tmp_path / "x.mp4")
    from news_documentary.persistence.storage import get_storage

    st = get_storage(str(tmp_path))
    assert st.name == "local" and st.ref("j1", "documentary.mp4") == "j1/documentary.mp4"
