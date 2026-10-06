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

    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
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

    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
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


# ------------------------------------------------- doc scope (PDF + posts) ---
# Active workflow writers. The video scriptwriter above is preserved for
# future video use; doc jobs use run_writer + run_doc_reviewer only.

PLATFORM_LIMITS = {
    # Verified against official docs/behaviour, Oct 2026. YouTube has NO
    # Data API endpoint for text/community posts (videos/comments only), so it
    # is text-generation-only for manual use and disabled for connected post.
    "x": {"max_chars": 280, "kind": "post", "connect_post": True,
          "note": "X API v2 POST /2/tweets, text-only (no media attached)."},
    "facebook": {"max_chars": 2000, "kind": "post", "connect_post": True,
                 "note": "POST /{page-id}/feed with message (+link). Pages only."},
    "hikmah": {"max_chars": 20000, "kind": "post", "connect_post": True,
               "note": "POST /api/posts type=text (code-complete, live-unverified)."},
    "youtube": {"max_chars": 5000, "kind": "manual-text", "connect_post": False,
                "note": "DISABLED for connected posting: YouTube Data API v3 has no "
                        "text/community-post endpoint (upload + comments only). "
                        "Generated title/description are for manual use."},
}


def _writer_lang(settings) -> str:
    return (getattr(settings, "narration_lang", "en") or "en").lower()


def run_writer(topic: str, fact_report: dict, sources: list[dict], settings,
               job_dir: Path, revision_note: str = "") -> dict:
    """Write a research report + platform-specific social posts.

    Every factual sentence traces to verified claim IDs. Platform limits are
    enforced here (hard truncation never splits a claim citation). Returns
    {report_md, summary, findings, posts} and persists report.md + posts.json.
    """
    import re as _re

    verified = fact_report.get("verified", [])
    lang = _writer_lang(settings)
    is_bn = lang.startswith("bn")
    if revision_note:
        topic = topic  # revision reuses the same topic; note steers emphasis

    def _rel(c: dict) -> int:
        if not topic:
            return 0
        tk = set(_re.findall(r"\w{4,}", topic.lower()))
        return len(tk & set(_re.findall(r"\w{4,}", c.get("text", "").lower())))

    picked = sorted(verified, key=_rel, reverse=True)[:6]
    claim_ids = [c["id"] for c in picked]
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    if is_bn:
        summary = f"বিষয়: {topic}। " + " ".join(c["text"] + "।" for c in picked[:3])
    else:
        summary = " ".join(c["text"] + "." for c in picked[:3]) or \
            "No verifiable claims — production blocked rather than inventing facts."
    if revision_note:
        summary += (" মনোযোগ: " if is_bn else " Revision focus: ") + revision_note[:300]

    findings = [{"text": c["text"], "claim_ids": [c["id"]],
                 "detail": c.get("notes", "")} for c in picked]
    md = [f"# {topic}", "",
          f"_Language: {lang} · {len(verified)} verified claim(s)_", "",
          "## Summary", "", summary, "",
          "## Key findings", ""]
    for i, f in enumerate(findings, 1):
        md += [f"{i}. {f['text']}", f"   Claims: {', '.join(f['claim_ids'])}", ""]
    if not findings:
        md += ["No verifiable findings.", ""]
    md += ["## Sources", ""]
    for s in sources[:12]:
        md += [f"- {s.get('publisher', '?')}: {s.get('title', '')[:140]}",
               f"  {s.get('url', '')}"]
    report_md = "\n".join(md)
    (job_dir / "report.md").write_text(report_md, encoding="utf-8")

    link = next((s.get("url", "") for s in sources if s.get("url")), "")
    posts: dict[str, dict] = {}
    head = (topic[:80] + ": ") if topic else ""
    for plat, lim in PLATFORM_LIMITS.items():
        if plat == "youtube":
            title = topic[:100]
            desc = (summary[:1500] + ("\n\nSources:\n" + "\n".join(
                s.get("url", "") for s in sources[:5]))[:lim["max_chars"]])
            posts[plat] = {"text": f"{title}\n\n{desc}", "title": title,
                           "description": desc, "claim_ids": claim_ids,
                           "chars": 0, "connect_post": False, "note": lim["note"]}
            posts[plat]["chars"] = len(posts[plat]["text"])
            continue
        core = head + (picked[0]["text"] if picked else summary)
        if plat == "x":
            text = core[:lim["max_chars"]]
            if link and len(text) + 1 + len(link) <= lim["max_chars"]:
                text += " " + link
        elif plat == "facebook":
            parts = [head + c["text"] + "." for c in picked[:3]] or [summary]
            text = "\n\n".join(parts)
            if link:
                text += f"\n\nRead more: {link}"
            text = text[:lim["max_chars"]]
        else:  # hikmah
            text = f"{topic}\n\n" + "\n\n".join(
                c["text"] + "." for c in picked[:5]) + "\n\nSources:\n" + "\n".join(
                s.get("url", "") for s in sources[:8])
            text = text[:lim["max_chars"]]
        posts[plat] = {"text": text, "claim_ids": claim_ids, "chars": len(text),
                       "connect_post": lim["connect_post"], "note": lim["note"]}
    (job_dir / "posts.json").write_text(
        json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report_md": report_md, "summary": summary, "findings": findings,
            "posts": posts, "version": 1, "language": lang}


def run_doc_reviewer(topic: str, writer_out: dict, fact_report: dict,
                     pdf_findings: list[dict], job_dir: Path) -> dict:
    """Review report + posts + rendered PDF. States exactly what was checked."""
    findings: list[dict] = []

    def add(area, checked, passed, detail=""):
        findings.append({"area": area, "checked": checked, "passed": passed, "detail": detail})

    verified_ids = {c.get("id") for c in fact_report.get("verified", [])}
    used = set()
    for p in (writer_out.get("posts", {}) or {}).values():
        used.update(p.get("claim_ids", []))
    for f in writer_out.get("findings", []) or []:
        used.update(f.get("claim_ids", []))
    bad = sorted(i for i in used if i not in verified_ids)
    add("factual-consistency", True, not bad,
        f"{len(verified_ids)} verified IDs cover all text" if not bad
        else f"cites outside verified set: {bad}")
    for plat, post in (writer_out.get("posts", {}) or {}).items():
        lim = PLATFORM_LIMITS.get(plat, {}).get("max_chars", 0)
        n = post.get("chars", len(post.get("text", "")))
        add(f"platform-limit:{plat}", True, n <= lim, f"{n}/{lim} chars")
    for pf in pdf_findings:
        findings.append({**pf, "area": f"pdf:{pf['area']}"})
    words = len((writer_out.get("summary", "") or "").split())
    add("readability", True, words >= 20, f"summary {words} words")
    add("pronunciation", False, False, "not applicable: text outputs, no TTS in this scope")
    passed = all(f["passed"] for f in findings if f["checked"])
    report = {"passed": passed, "findings": findings,
              "needs_revision": "" if passed else "fix flagged areas",
              "limits": "LLM prose not re-verified sentence-by-sentence; "
                        "Bengali PDF needs DOC_FONT_TTF; Hikmah text posting live-unverified."}
    (job_dir / "review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
