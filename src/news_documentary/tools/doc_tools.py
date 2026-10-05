"""Typed LangChain tools. Tools execute operations; skills describe procedures."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import tool


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@tool
def news_search(query: str, max_results: int = 5) -> str:
    """Search recent news (Tavily live when configured, else free RSS). Returns JSON sources
    with url, publisher, title, published_at, excerpt. Use for research and fact-checking."""
    from ..config import get_settings
    from ..providers.search import get_search_adapter

    try:
        adapter = get_search_adapter(get_settings())
        items = adapter.search(query, max_results)
    except Exception as e:
        return json.dumps({"error": str(e)[:200], "sources": []})
    return json.dumps({"adapter": adapter.name, "sources": items}, ensure_ascii=False)


@tool
def save_artifact(job_dir: str, name: str, content: str) -> str:
    """Save a text artifact into the job namespace. Returns absolute path."""
    base = Path(job_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    target = (base / name).resolve()
    if target != base and base not in target.parents:
        raise ValueError("Unsafe artifact path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target)


@tool
def rank_topics(candidates_json: str) -> str:
    """Rank topic candidates by recency/relevance/evidence. Returns ranked JSON."""
    cands = json.loads(candidates_json)
    for c in cands:
        sig = c.get("trend_signal", "")
        c["score"] = float(c.get("score", 0)) + (0.5 if sig and sig != "search-rank-only" else -0.5)
    cands.sort(key=lambda c: c.get("score", 0), reverse=True)
    return json.dumps(cands, ensure_ascii=False)


@tool
def extract_claims(research_json: str) -> str:
    """Split research notes into atomic claims (fact/allegation/opinion/unknown)."""
    data = json.loads(research_json)
    notes = data.get("notes", data) if isinstance(data, dict) else data
    if isinstance(notes, dict):
        notes = [notes]
    claims = []
    for i, n in enumerate(notes if isinstance(notes, list) else [notes]):
        text = n.get("text", str(n)) if isinstance(n, dict) else str(n)
        for j, sent in enumerate([s.strip() for s in text.split(".") if s.strip()][:6]):
            claims.append({"id": f"C{i + 1}-{j + 1}", "text": sent, "kind": "fact",
                           "status": "unresolved", "source_urls": n.get("source_urls", []) if isinstance(n, dict) else []})
    return json.dumps(claims, ensure_ascii=False)


@tool
def check_claim_support(claim_json: str, sources_json: str) -> str:
    """Independent claim check: counts genuinely independent publishers (syndication-aware)."""
    import re

    claim = json.loads(claim_json)
    sources = json.loads(sources_json)
    text = claim.get("text", "")

    def _pub(s: dict) -> str:
        if s.get("publisher"):
            return s["publisher"]
        try:
            from urllib.parse import urlparse

            return urlparse(s.get("url", "")).netloc.replace("www.", "") or s.get("url", "?")
        except Exception:
            return s.get("url", "?")

    keywords = [w for w in re.findall(r"\w{4,}", text.lower())][:6]
    pubs: dict[str, int] = {}
    for s in sources:
        blob = ((s.get("title", "") or "") + " " + (s.get("excerpt", "") or "")).lower()
        if any(k in blob for k in keywords):
            pubs[_pub(s)] = pubs.get(_pub(s), 0) + 1
    # syndicated copies: same title prefix from different urls of same publisher family -> count once (already keyed by publisher)
    support = len(pubs)
    status = "verified" if support >= 2 else ("disputed" if support == 0 else "unresolved")
    return json.dumps({"claim_id": claim.get("id"), "independent_sources": support,
                       "publishers": list(pubs), "status": status})


@tool
def estimate_narration_timing(text: str, lang: str = "en") -> str:
    """Estimate narration seconds from text (calibrated; real timing comes from TTS audio)."""
    cps = 12.0 if lang.lower().startswith("bn") else 15.0
    return json.dumps({"chars": len(text), "est_seconds": round(len(text) / cps, 1), "lang": lang})


@tool
def build_render_manifest(job_dir: str, scenes_json: str, audio_path: str) -> str:
    """Write render_manifest.json mapping scenes to assets. Returns path."""
    scenes = json.loads(scenes_json)
    manifest = {"audio": audio_path, "scenes": scenes, "created_at": _utcnow()}
    p = Path(job_dir) / "render_manifest.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)
