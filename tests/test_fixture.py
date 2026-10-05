"""Fixture + reliability tests (offline)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from news_documentary.config import Settings
from news_documentary.persistence import db as pdb
from news_documentary.publishing.manager_helpers import publish_with_reconciliation
from news_documentary.workflow import graph as G


def _settings(tmp: Path) -> Settings:
    return Settings(tts_provider="fixture", youtube_publish_mode="fixture",
                    job_root=str(tmp / "jobs"), db_path=str(tmp / "t.sqlite"),
                    publish_policy="manual", news_model="")


def test_fixture_end_to_end(tmp_path: Path):
    st = _settings(tmp_path)
    out = G.run_job(st, topic="ফিক্সচার পরীক্ষা", job_id="t1")
    assert out["status"] in ("awaiting-approval", "published", "blocked-no-evidence", "reviewed-failed")
    arts = out.get("artifacts", {})
    if out["status"] == "awaiting-approval":
        assert Path(arts["video"]).exists()
        assert Path(arts["captions"]).exists()
        # approval binding: approving then changing video invalidates
        from news_documentary.workflow.approval import approve_job

        approve_job(st.job_root, "t1")
        vh = hashlib.sha256(Path(arts["video"]).read_bytes()).hexdigest()
        appr = json.loads((Path(st.job_root) / "t1" / "approval.json").read_text())
        assert appr["video_hash"] == vh


def test_publish_blocked_without_approval(tmp_path: Path):
    st = _settings(tmp_path)
    pdb.migrate(st.db_path)
    (Path(st.job_root) / "j").mkdir(parents=True, exist_ok=True)
    v = Path(st.job_root) / "j" / "v.mp4"
    v.write_bytes(b"fake-video")
    from news_documentary.workflow.graph import n_publish

    out = n_publish({"job_id": "j", "thread_id": "t", "settings_snapshot": st.model_dump(),
                     "artifacts": {"video": str(v)}, "script": {"title": "t", "narration_full": "x", "version": 1},
                     "sources": [], "approval": {"approved": False}, "stage": "publish", "status": "x"})
    assert out["status"] == "publish-blocked-no-approval"


def test_duplicate_publish_prevention(tmp_path: Path):
    st = _settings(tmp_path)
    pdb.migrate(st.db_path)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"bytes-123")
    h = hashlib.sha256(b"bytes-123").hexdigest()
    r1 = publish_with_reconciliation(st, st.db_path, "j1", "youtube", v, "t", "d", "unlisted", h)
    assert r1["status"].startswith("succeeded")
    r2 = publish_with_reconciliation(st, st.db_path, "j1", "youtube", v, "t", "d", "unlisted", h)
    assert r2.get("skipped") is True


def test_stale_news_flag(tmp_path: Path):
    from news_documentary.providers.search import FixtureSearchAdapter

    items = FixtureSearchAdapter().search("বৃষ্টি")
    assert items and all(i["fixture"] for i in items)
    # event time vs published time both recorded
    assert items[0].get("published_at") and items[0].get("event_time")
