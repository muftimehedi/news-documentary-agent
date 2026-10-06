"""Accounts + connected publishing tests (offline; network adapters mocked)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from news_documentary.config import Settings
from news_documentary.media.bundle import build_manual_bundle
from news_documentary.persistence import vault as V
from news_documentary.publishing import service as pub
from news_documentary.publishing.adapters import ADAPTERS, AdapterError, get_adapter


@pytest.fixture()
def st(tmp_path: Path) -> Settings:
    return Settings(tts_provider="fixture", youtube_publish_mode="fixture",
                    job_root=str(tmp_path / "jobs"), db_path=str(tmp_path / "t.sqlite"),
                    publish_policy="manual", news_model="", narration_lang="en")


def _mkjob(st: Settings, jid: str) -> Path:
    jd = Path(st.job_root) / jid
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "documentary.mp4").write_bytes(b"fake-video-bytes-" + jid.encode())
    (jd / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHello world\n", encoding="utf-8")
    (jd / "script.json").write_text(json.dumps({"title": "T", "narration_full": "Hello world",
                                                "language": "en", "scenes": [], "version": 1}))
    (jd / "sources.json").write_text(json.dumps([{"url": "https://example.com/a"}]))
    return jd


def _connect(st: Settings, owner: str, platform: str, label: str) -> dict:
    return V.connect_account(st.db_path, owner, platform, label,
                             {"tok": "SECRET-ABCDEFGH"}, {"account": label})


def _pubs(st: Settings):
    from news_documentary.persistence import db as pdb

    pdb.migrate(st.db_path)
    c = sqlite3.connect(st.db_path)
    rows = c.execute("SELECT logical_key,status FROM publications").fetchall()
    c.close()
    return rows


# 1. No connected accounts needed to generate + download ---------------------
def test_manual_bundle_without_accounts(st: Settings):
    _mkjob(st, "j1")
    b = build_manual_bundle(st.job_root, "j1", "My Title", "My desc")
    assert "video_mp4" in b and "metadata_txt" in b
    txt = Path(b["metadata_txt"]).read_text(encoding="utf-8")
    assert "My Title" in txt and "My desc" in txt and "https://example.com/a" in txt
    assert _pubs(st) == []  # downloading publishes nothing


# 2. Connecting never publishes ----------------------------------------------
def test_connect_creates_no_receipts(st: Settings):
    info = get_adapter("fixture").verify({})
    V.connect_account(st.db_path, "alice", "fixture", "t", {"tok": "SECRET-ABCDEFGH"}, info)
    assert _pubs(st) == []


# 3/7. Only the reviewed artifact publishes; changes need a new review ------
def test_tampered_video_and_metadata_blocked(st: Settings):
    _mkjob(st, "j2")
    acc = _connect(st, "alice", "fixture", "f1")
    pub.save_meta(st.job_root, "alice", "j2", "Title", "Desc")
    pub.build_review(st.db_path, "alice", st.job_root, "j2",
                     [{"account_id": acc["id"], "platform": "fixture", "visibility": "public"}])
    (Path(st.job_root) / "j2" / "documentary.mp4").write_bytes(b"tampered!")
    with pytest.raises(AdapterError, match="changed after review"):
        pub.publish_reviewed(st.db_path, "alice", st.job_root, "j2")
    # restore video, then change metadata instead
    (Path(st.job_root) / "j2" / "documentary.mp4").write_bytes(b"fake-video-bytes-j2")
    pub.save_meta(st.job_root, "alice", "j2", "DIFFERENT title", "Desc")
    with pytest.raises(AdapterError, match="authorize again"):
        pub.publish_reviewed(st.db_path, "alice", st.job_root, "j2")
    assert _pubs(st) == []


# 4/8. Partial failure isolation + retry only failed --------------------------
def test_partial_failure_and_retry(st: Settings, monkeypatch):
    _mkjob(st, "j3")
    a1 = _connect(st, "alice", "fixture", "f1")
    a2 = _connect(st, "alice", "hikmah", "h1")
    pub.save_meta(st.job_root, "alice", "j3", "T", "short desc")
    pub.build_review(st.db_path, "alice", st.job_root, "j3", [
        {"account_id": a1["id"], "platform": "fixture", "visibility": "public"},
        {"account_id": a2["id"], "platform": "hikmah", "visibility": "public"}])

    def boom(*a, **k):
        raise AdapterError("hikmah down", permanent=True)

    monkeypatch.setattr(ADAPTERS["hikmah"], "upload", boom)
    res = pub.publish_reviewed(st.db_path, "alice", st.job_root, "j3")
    by_plat = {r["platform"]: r for r in res}
    assert by_plat["fixture"]["status"].startswith("succeeded")  # success kept
    assert by_plat["hikmah"]["status"] == "failed-permanent"

    def good(video, title, desc, vis, creds, job_id=""):
        return {"destination": "hikmah", "remote_id": "H-1", "url": "https://hikmah.test/p/1",
                "visibility": vis, "status": "succeeded", "timestamp": "t", "fixture": False}

    monkeypatch.setattr(ADAPTERS["hikmah"], "upload", good)
    res2 = pub.retry_failed(st.db_path, "alice", st.job_root, "j3")
    by2 = {r["platform"]: r for r in res2}
    assert by2["fixture"].get("skipped") is True  # winner never re-uploaded
    assert by2["hikmah"]["status"] == "succeeded"


# 5. Owner isolation ----------------------------------------------------------
def test_owner_isolation(st: Settings):
    _mkjob(st, "j4")
    acc = _connect(st, "alice", "fixture", "f1")
    assert V.list_accounts(st.db_path, "bob") == []
    assert V.get_account(st.db_path, "bob", acc["id"]) is None
    pub.save_meta(st.job_root, "alice", "j4", "T", "D")
    with pytest.raises(AdapterError, match="not connected"):
        pub.build_review(st.db_path, "bob", st.job_root, "j4",
                         [{"account_id": acc["id"], "platform": "fixture", "visibility": "public"}])
    pub.build_review(st.db_path, "alice", st.job_root, "j4",
                     [{"account_id": acc["id"], "platform": "fixture", "visibility": "public"}])
    with pytest.raises(AdapterError, match="another owner"):
        pub.publish_reviewed(st.db_path, "bob", st.job_root, "j4")


# 6. Disconnected accounts cannot publish ------------------------------------
def test_disconnected_blocked(st: Settings):
    _mkjob(st, "j5")
    acc = _connect(st, "alice", "fixture", "f1")
    pub.save_meta(st.job_root, "alice", "j5", "T", "D")
    assert V.disconnect_account(st.db_path, "alice", acc["id"]) is True
    with pytest.raises(AdapterError, match="not connected"):
        pub.build_review(st.db_path, "alice", st.job_root, "j5",
                         [{"account_id": acc["id"], "platform": "fixture", "visibility": "public"}])


def test_secrets_redacted_and_locked_down(st: Settings):
    acc = _connect(st, "alice", "x", "x1")
    p = V.vault_path(st.db_path, acc["id"])
    assert (p.stat().st_mode & 0o777) == 0o600
    red = V.redact({"access_token": "SECRET-ABCDEFGH", "label": "x1"})
    assert "SECRET" not in str(red) and red["label"] == "x1"
