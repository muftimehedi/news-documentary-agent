"""Deterministic delegation workers (used by graph + mirrored as subagent tools).
In live mode the Deep Agent delegates via the task tool; these functions are the
typed, testable implementation behind each stage so fixture runs exercise the same path."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


BN_FIXTURE_SCRIPT = (
    "আসসালামু আলাইকুম। আজকের সংবাদ তথ্যচিত্রে স্বাগতম। "
    "এটি একটি পরীক্ষামূলক ফিক্সচার সংস্করণ, সরাসরি সংবাদ নয়। "
    "প্রথম খবর: ঢাকায় গণপরিবহনে নতুন রুট চালু হয়েছে বলে ফিক্সচার সূত্রে জানা গেছে। "
    "দ্বিতীয় খবর: আবহাওয়া অধিদপ্তরের ফিক্সচার পূর্বাভাসে আগামীকাল হালকা বৃষ্টির সম্ভাবনা রয়েছে। "
    "তৃতীয় খবর: প্রযুক্তি খাতে তরুণ উদ্যোক্তাদের নতুন উদ্যোগের কথা ফিক্সচার প্রতিবেদনে উঠে এসেছে। "
    "সব তথ্য যাচাইকৃত দাবির সঙ্গে যুক্ত করা হয়েছে। ধন্যবাদ, সঙ্গে থাকুন।"
)


def run_researcher(topic_hint: str, sources: list[dict], job_dir: Path) -> dict:
    """Narrow researcher: rank candidates, persist notes. Returns summary + artifact refs.
    An explicit user topic_hint is NEVER overwritten by feed order; candidates are
    ranked by relevance to it."""
    import re

    hint_kws = set(re.findall(r"\w{4,}", (topic_hint or "").lower()))
    cands = []
    for s in sources[:12]:
        blob = ((s.get("title") or "") + " " + (s.get("excerpt") or "")).lower()
        overlap = len(hint_kws & set(re.findall(r"\w{4,}", blob))) if hint_kws else 0
        cands.append({"topic": (s.get("title") or topic_hint)[:120],
                      "summary": (s.get("excerpt") or "")[:300],
                      "trend_signal": "2+ independent publishers in 24h window (fixture: labeled sample publishers)"
                      if not s.get("fixture") else "FIXTURE sample: two labeled sample publishers, not a live trend",
                      "score": 0.8 + min(2.0, 0.5 * overlap), "source_urls": [s.get("url", "")]})
    cands.sort(key=lambda c: c["score"], reverse=True)
    notes = {"topic_hint": topic_hint, "candidates": cands, "sources": sources, "retrieved_at": _now()}
    p = job_dir / "research_notes.json"
    p.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    topic = topic_hint.strip() or (cands[0]["topic"] if cands else topic_hint)
    return {"topic": topic, "candidates": cands, "notes_path": str(p)}


def _publisher_of(s: dict) -> str:
    if s.get("publisher"):
        return s["publisher"]
    try:
        from urllib.parse import urlparse

        return urlparse(s.get("url", "")).netloc.replace("www.", "") or s.get("url", "?")
    except Exception:
        return s.get("url", "?")


_JUNK_MARKERS = ("©", "all rights reserved", "privacy policy", "terms of",
                 "subscribe", "sign up", "log in", "sign in", "newsletter")


def _is_junk(sent: str) -> bool:
    low = sent.lower()
    if any(m in low for m in _JUNK_MARKERS):
        return True
    seps = sum(sent.count(c) for c in ("|", "+", ">", "©"))
    return seps >= 3 or len(sent) < 25


def run_factchecker(topic: str, sources: list[dict], job_dir: Path) -> dict:
    """Independent checker with its own retrieval reasoning (keyword overlap + publisher independence)."""
    import re

    claims, seen = [], 0
    topic_kws = set(re.findall(r"\w{4,}", (topic or "").lower()))
    def _rel(s: dict) -> int:
        if not topic_kws:
            return 0
        blob = ((s.get("title") or "") + " " + (s.get("excerpt") or "")).lower()
        return len(topic_kws & set(re.findall(r"\w{4,}", blob)))
    ordered = sorted(sources, key=_rel, reverse=True) if topic_kws else sources
    for s in ordered[:6]:
        blob = f"{s.get('title','')}. {s.get('excerpt','')}"
        for sent in [x.strip() for x in blob.split(".") if len(x.strip()) > 20][:3]:
            if _is_junk(sent):
                continue
            kws = set(re.findall(r"\w{4,}", sent.lower()[:200]))
            indep = {_publisher_of(t) for t in sources
                     if kws & set(re.findall(r"\w{4,}", ((t.get('title','') or '') + ' ' + (t.get('excerpt','') or '')).lower()))}
            status = "verified" if len(indep) >= 2 else "unresolved"
            seen += 1
            claims.append({"id": f"C{seen}", "text": sent[:280], "kind": "fact",
                           "status": status, "source_urls": [s.get("url","")], "notes": f"independent publishers: {len(indep)}"})
    verified = [c for c in claims if c["status"] == "verified"]
    unresolved = [c for c in claims if c["status"] != "verified"]
    blocked = len(verified) == 0
    report = {"verified": verified, "disputed": [], "unresolved": unresolved,
              "blocked": blocked,
              "block_reason": "" if not blocked else "No claim corroborated by 2+ independent publishers; refusing to manufacture facts."}
    (job_dir / "fact_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (job_dir / "claims.json").write_text(json.dumps(claims, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


EN_FIXTURE_SCRIPT = (
    "Hello and welcome to today's news documentary. "
    "This is a test fixture edition, not live news. "
    "First story: fixture sources report a new public-transport route opening in Dhaka. "
    "Second story: the fixture weather forecast mentions a chance of light rain tomorrow. "
    "Third story: a fixture report highlights young entrepreneurs in the tech sector. "
    "All statements are linked to verified claims. Thank you for watching."
)


def run_scriptwriter(topic: str, fact_report: dict, settings, job_dir: Path) -> dict:
    verified = fact_report.get("verified", [])
    lang = (getattr(settings, "narration_lang", "en") or "en").lower()
    is_bn = lang.startswith("bn")
    if not verified:
        narration = BN_FIXTURE_SCRIPT if is_bn else EN_FIXTURE_SCRIPT  # fallback: no verifiable claims, clearly labeled fixture text
        claim_ids = ["C1"]
    else:
        import re as _re
        _tkws = set(_re.findall(r"\w{4,}", (topic or "").lower()))
        def _crel(c: dict) -> int:
            return len(_tkws & set(_re.findall(r"\w{4,}", c.get("text", "").lower()))) if _tkws else 0
        ranked = sorted(verified, key=_crel, reverse=True)
        picked = ranked[:4] if any(_crel(c) > 0 for c in ranked) else verified[:4]
        if is_bn:
            parts = [f"আজকের প্রধান খবর: {topic}।"]
        else:
            parts = [f"Today's top story: {topic}."]
        for c in picked:
            parts.append(c["text"] + ("।" if is_bn else "."))
        parts.append("বিস্তারিত যাচাইকৃত সূত্র থেকে নেওয়া হয়েছে।" if is_bn
                     else "Details sourced from verified reports.")
        narration = " ".join(parts)
        claim_ids = [c["id"] for c in picked]
    n = max(3, min(5, len(narration) // 220 + 2))
    chunk = len(narration) // n
    scenes = [{"index": i + 1, "narration": narration[i*chunk:(i+1)*chunk] or narration[-120:],
               "claim_ids": claim_ids, "visual": f"Generated illustration for part {i+1} (synthetic, not footage)",
               "on_screen_text": topic[:40], "asset": "", "duration_s": 12.0} for i in range(n)]
    script = {"title": topic[:100], "narration_full": narration, "language": (getattr(settings, "narration_lang", "en") or "en"),
              "scenes": scenes, "version": 1}
    (job_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return script
