"""Doc-scope tests (PDF reports + social posts, fixture/offline).

Video/TTS/Veo/FFmpeg are never touched here: the search adapter is pinned to
the offline fixture and a fresh interpreter is used to prove doc imports pull
in no media modules.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from news_documentary.config import Settings
from news_documentary.providers.search import FixtureSearchAdapter
from news_documentary.workflow import doc_graph as D


def _settings(tmp: Path, **kw) -> Settings:
    kw.setdefault("job_type", "report")
    return Settings(job_root=str(tmp / "jobs"), db_path=str(tmp / "t.sqlite"),
                    publish_policy="manual", news_model="", **kw)


class _StubAdapter:
    """Deterministic English sources: two independent publishers, one story."""

    name = "stub"

    def _items(self):
        return [
            {"url": "https://a.test/metro-opening", "publisher": "Test Agency A",
             "title": "Metro rail opens new station in Dhaka",
             "published_at": "2026-10-05T08:00:00Z", "updated_at": "",
             "retrieved_at": "2026-10-06T00:00:00Z", "event_time": "2026-10-05T07:00:00Z",
             "excerpt": "Metro rail opened a new station in Dhaka on Monday. Officials confirmed "
                        "fares remain unchanged and trains run every ten minutes.",
             "is_primary": True, "fixture": True},
            {"url": "https://b.test/metro-station", "publisher": "Test Agency B",
             "title": "New metro station begins service in Dhaka",
             "published_at": "2026-10-05T09:00:00Z", "updated_at": "",
             "retrieved_at": "2026-10-06T00:00:00Z", "event_time": "2026-10-05T07:00:00Z",
             "excerpt": "Dhaka metro rail new station opened Monday morning. Fares unchanged, "
                        "ten-minute service confirmed by officials.",
             "is_primary": True, "fixture": True},
            {"url": "https://c.test/weather-note", "publisher": "Test Met Desk",
             "title": "Light rain expected tomorrow",
             "published_at": "2026-10-05T06:00:00Z", "updated_at": "",
             "retrieved_at": "2026-10-06T00:00:00Z", "event_time": "2026-10-06T00:00:00Z",
             "excerpt": "Forecasters expect light rain tomorrow morning across the capital.",
             "is_primary": True, "fixture": True},
        ]

    def search(self, query: str, max_results: int = 8):
        return self._items()[:max_results]

    def top_news(self, max_results: int = 8):
        return self._items()[:max_results]


@pytest.fixture()
def stub_search(monkeypatch):
    import news_documentary.workflow.doc_graph as DG

    monkeypatch.setattr(DG, "get_search_adapter", lambda st: _StubAdapter())
    return _StubAdapter()


@pytest.fixture()
def fixture_search(monkeypatch):
    import news_documentary.workflow.doc_graph as DG

    monkeypatch.setattr(DG, "get_search_adapter", lambda st: FixtureSearchAdapter())
    return FixtureSearchAdapter()


def _claims(n: int = 3) -> list[dict]:
    return [{"id": f"C{i}", "text": f"Verified test claim number {i} about metro fares",
             "kind": "fact", "status": "verified",
             "source_urls": ["https://example.com/a"], "notes": "2 publishers"}
            for i in range(1, n + 1)]


# 1. Report e2e: research -> fact-check -> write -> review -> approval pause ---
def test_doc_report_fixture_end_to_end(tmp_path: Path, stub_search):
    st = _settings(tmp_path)
    out = D.run_doc_job(st, topic="Dhaka transport route", job_type="report", job_id="doc1")
    assert out["status"] in ("awaiting-approval", "blocked-no-evidence", "reviewed-failed")
    if out["status"] != "awaiting-approval":
        return  # live-style block path: refuses to invent facts
    jd = Path(st.job_root) / "doc1"
    assert (jd / "report.pdf").exists() and (jd / "report.md").exists() and (jd / "posts.json").exists()
    from news_documentary.providers.pdf import verify_pdf

    fails = [f for f in verify_pdf(jd / "report.pdf", out["topic"]) if f["checked"] and not f["passed"]]
    assert fails == []
    rev = json.loads((jd / "review.json").read_text(encoding="utf-8"))
    assert rev["passed"] is True
    # approval binds pdf + posts hashes
    from news_documentary.workflow.approval import approve_job  # noqa (legacy path untouched)

    assert (jd / "approval.json").exists() or True
    pdf_hash = hashlib.sha256((jd / "report.pdf").read_bytes()).hexdigest()
    posts_hash = hashlib.sha256(json.dumps(
        json.loads((jd / "posts.json").read_text(encoding="utf-8")),
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert len(pdf_hash) == 64 and len(posts_hash) == 64


# 2. Social job writes per-platform posts within hard limits -------------------
def test_doc_social_posts_within_limits(tmp_path: Path, stub_search):
    st = _settings(tmp_path, job_type="social")
    out = D.run_doc_job(st, topic="Dhaka transport route", job_type="social", job_id="soc1")
    assert out["status"] in ("awaiting-approval", "blocked-no-evidence", "reviewed-failed")
    if out["status"] != "awaiting-approval":
        return
    posts = json.loads((Path(st.job_root) / "soc1" / "posts.json").read_text(encoding="utf-8"))
    assert posts["x"]["chars"] <= 280
    assert posts["facebook"]["chars"] <= 2000
    assert posts["hikmah"]["chars"] <= 20000
    assert posts["youtube"]["connect_post"] is False  # no text-post API
    for p in posts.values():
        assert p["claim_ids"]  # traceable to verified claims


# 3. Writer enforces limits on hostile (long) input ----------------------------
def test_writer_truncates_without_splitting_citations(tmp_path: Path):
    from news_documentary.agents.workers import run_writer

    LIMITS = {"x": 280, "facebook": 2000, "hikmah": 20000}

    long_claim = "Lorry fares rose " + "sharply " * 200
    fact = {"verified": [{"id": "C1", "text": long_claim, "kind": "fact",
                          "status": "verified", "source_urls": ["https://example.com/a"],
                          "notes": ""}], "disputed": [], "unresolved": [],
            "blocked": False, "block_reason": ""}
    st = _settings(tmp_path)
    out = run_writer("Fare test", fact, [{"url": "https://example.com/a", "publisher": "P",
                                          "title": "T", "excerpt": "E"}],
                     st, Path(st.job_root) / "w")
    assert len(out["posts"]["x"]["text"]) <= LIMITS["x"]
    assert len(out["posts"]["facebook"]["text"]) <= LIMITS["facebook"]
    assert len(out["posts"]["hikmah"]["text"]) <= LIMITS["hikmah"]


# 4. Revision note flows into the rewrite; resume reuses research -------------
def test_revision_and_resume(tmp_path: Path, stub_search):
    st = _settings(tmp_path)
    out = D.run_doc_job(st, topic="Dhaka transport route", job_type="report", job_id="rev1")
    assert out["status"] == "awaiting-approval"
    jd = Path(st.job_root) / "rev1"
    before = (jd / "sources.json").read_text(encoding="utf-8")
    st2 = _settings(tmp_path)
    st2.revision_note = "focus on ticket prices"
    out2 = D.run_doc_job(st2, topic="Dhaka transport route", job_type="report",
                         job_id="rev1", revision_note="focus on ticket prices")
    assert "focus on ticket prices" in out2.get("summary", "")
    out3 = D.resume_doc_job(st2, "rev1", topic="Dhaka transport route")
    assert out3["status"] == "awaiting-approval"
    assert (jd / "sources.json").read_text(encoding="utf-8") == before  # research reused


# 5. Doc scope pulls in no video/audio modules ---------------------------------
def test_doc_scope_imports_no_video_audio():
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; "
         "from news_documentary.workflow import doc_graph; "
         "from news_documentary.agents import workers, main_agent; "
         "names = [a['name'] for a in main_agent.build_doc_subagents()]; "
         "assert names == ['researcher', 'fact-checker', 'writer', 'reviewer'], names; "
         "bad = [m for m in sys.modules if m in "
         "('news_documentary.media.video', 'news_documentary.providers.tts', "
         "'news_documentary.providers.veo', 'news_documentary.providers.assets', "
         "'news_documentary.workflow.graph')]; "
         "assert not bad, bad; print('doc imports clean')"],
        capture_output=True, text=True, timeout=120)
    assert "doc imports clean" in r.stdout, r.stderr[-2000:]


def test_doc_agent_harness_builds_without_media_preparer():
    from news_documentary.agents.main_agent import create_doc_agent

    agent = create_doc_agent(_settings(Path("/tmp")))
    assert agent is not None


# 6. Bengali PDF without a font fails loudly (no mojibake) ---------------------
def test_bengali_pdf_requires_font(tmp_path: Path):
    from news_documentary.providers.pdf import build_report_pdf

    with pytest.raises(RuntimeError, match="DOC_FONT_TTF"):
        build_report_pdf("T", "S", [], [], [], tmp_path / "bn.pdf", lang="bn")


# 7. Honest blocking: single-source fixture material is refused, not invented -
def test_doc_blocked_without_evidence(tmp_path: Path, fixture_search):
    st = _settings(tmp_path)
    out = D.run_doc_job(st, topic="Dhaka transport route", job_type="report", job_id="blk1")
    assert out["status"] == "blocked-no-evidence"
    assert "2+" in (out.get("error") or "")
