"""PDF report provider: real downloadable PDF reports (no video/audio/FFmpeg).

Uses fpdf2 (pure Python). English default with core fonts; Bengali ("bn")
needs a Unicode TTF with Bengali glyphs — see DOC_FONT_TTF. When unavailable
the run fails loudly with setup steps instead of producing mojibake.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


def _font_setup(pdf, lang: str) -> tuple[str, bool]:
    """Returns (family, is_unicode). Raises with setup steps when bn lacks a font."""
    if not (lang or "en").lower().startswith("bn"):
        pdf.set_font("Helvetica", size=11)
        return "Helvetica", False
    ttf = os.environ.get("DOC_FONT_TTF", "")
    if ttf and Path(ttf).exists():
        pdf.add_font("DocUnicode", "", ttf)
        return "DocUnicode", True
    raise RuntimeError(
        "Bengali PDF needs a Unicode TTF with Bengali glyphs: set DOC_FONT_TTF=/path/font.ttf "
        "(e.g. NotoSansBengali-Regular.ttf). Refusing to render unreadable text."
    )


_LATIN1_MAP = {
    "•": "-", "—": "--", "–": "-", "·": "-", """: '"', """: '"',
    "'": "'", "'": "'", "…": "...", "→": "->", "←": "<-", "✓": "v",
    "“": '"', "”": '"', "‘": "'", "’": "'",
}


def _latin1(text: str) -> str:
    """Core PDF fonts only cover latin-1: transliterate common punctuation
    instead of crashing on the first bullet or em dash."""
    out = "".join(_LATIN1_MAP.get(ch, ch) for ch in (text or ""))
    return out.encode("latin-1", errors="replace").decode("latin-1")


def _write_wrapped(pdf, family: str, text: str, size: int = 11, bold: bool = False,
                   color=(0, 0, 0)):
    from fpdf.enums import XPos, YPos

    pdf.set_font(family, "B" if bold else "", size)
    pdf.set_text_color(*color)
    if family == "Helvetica":
        text = _latin1(text)
    pdf.multi_cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def build_report_pdf(topic: str, summary: str, findings: list[dict], sources: list[dict],
                     claims: list[dict], out_path: Path, lang: str = "en",
                     fixture: bool = False) -> dict:
    """Render a formatted multi-page PDF. Returns {path, pages, size_bytes}."""
    from fpdf import FPDF

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    class Report(FPDF):
        def header(self):
            if self.page_no() == 1:
                return
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(100, 100, 100)
            self.cell(0, 8, _latin1(f"News Research Report - {topic[:60]}"), align="L")
            self.ln(10)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(100, 100, 100)
            self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    pdf = Report(format="A4")
    pdf.alias_nb_pages("{nb}")
    pdf.set_auto_page_break(True, margin=20)
    family, _unicode = _font_setup(pdf, lang)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pdf.add_page()
    _write_wrapped(pdf, family, "NEWS RESEARCH REPORT", 20, True, (20, 40, 90))
    _write_wrapped(pdf, family, topic, 14, True)
    _write_wrapped(pdf, family, f"Generated {now} · Language: {lang} · "
                         f"{'FIXTURE test data — not live news' if fixture else 'Live research'}", 9)
    pdf.ln(4)
    _write_wrapped(pdf, family, "Summary", 13, True, (20, 40, 90))
    _write_wrapped(pdf, family, summary or "(no summary — production was blocked)")
    pdf.ln(2)
    _write_wrapped(pdf, family, "Key findings (each linked to verified claim IDs)", 13, True, (20, 40, 90))
    if not findings:
        _write_wrapped(pdf, family, "No verifiable findings. Production was blocked rather than inventing facts.")
    for i, f in enumerate(findings, 1):
        _write_wrapped(pdf, family, f"{i}. {f.get('text', '')}", 11, True)
        cids = ", ".join(f.get("claim_ids", []) or [])
        if cids:
            _write_wrapped(pdf, family, f"   Claims: {cids}", 9)
        if f.get("detail"):
            _write_wrapped(pdf, family, f"   {f['detail']}", 10)
    pdf.ln(2)
    _write_wrapped(pdf, family, "Claim verification", 13, True, (20, 40, 90))
    if not claims:
        _write_wrapped(pdf, family, "No claims reached 'verified' with 2+ independent publishers.")
    for c in claims[:30]:
        _write_wrapped(pdf, family, f"[{c.get('id')}] ({c.get('status')}) {c.get('text', '')[:300]}", 10)
    pdf.ln(2)
    _write_wrapped(pdf, family, "Sources", 13, True, (20, 40, 90))
    for s in sources[:20]:
        line = f"• {s.get('publisher', '?')} — {s.get('title', '')[:120]}"
        _write_wrapped(pdf, family, line, 10)
        if s.get("url"):
            _write_wrapped(pdf, family, f"  {s['url']}", 8, color=(20, 60, 140))
        meta = "  " + " | ".join(x for x in (
            f"published: {s.get('published_at', '')}" if s.get("published_at") else "",
            f"event: {s.get('event_time', '')}" if s.get("event_time") else "",
            f"retrieved: {s.get('retrieved_at', '')}" if s.get("retrieved_at") else "",
        ) if x)
        if meta.strip():
            _write_wrapped(pdf, family, meta, 8)
    pdf.ln(2)
    _write_wrapped(pdf, family, "Methodology & limits", 13, True, (20, 40, 90))
    _write_wrapped(pdf, family,
        "Research used live retrieval (Tavily/RSS), never model memory. "
        "Fact-check re-fetched independently; syndicated copies do not count as "
        "independent corroboration. Unverified material is labeled, never asserted. "
        "Generated visuals are not part of this report.", 10)

    pdf.output(str(out_path))
    return {"path": str(out_path), "pages": pdf.page_no(),
            "size_bytes": out_path.stat().st_size, "fixture": fixture, "lang": lang}


def verify_pdf(pdf_path: Path, topic: str, min_sources: int = 1) -> list[dict]:
    """Inspect the rendered PDF: layout, readability, missing content.

    Checks page count/size, non-empty pages, title + Sources section present,
    source URLs present. Never passes on file existence alone.
    """
    from pypdf import PdfReader

    findings: list[dict] = []

    def add(area, checked, passed, detail=""):
        findings.append({"area": area, "checked": checked, "passed": passed, "detail": detail})

    if not Path(pdf_path).exists():
        add("output-exists", True, False, "report.pdf missing")
        return findings
    add("output-exists", True, True, str(pdf_path))
    try:
        reader = PdfReader(str(pdf_path))
        pages = len(reader.pages)
        add("page-count", True, pages >= 1, f"{pages} page(s)")
        if pages == 0:
            return findings
        box = reader.pages[0].mediabox
        w, h = float(box.width), float(box.height)
        # A4 ≈ 595 x 842 pt
        add("page-size", True, abs(w - 595.27) < 3 and abs(h - 841.89) < 3,
            f"{w:.1f} x {h:.1f} pt (want A4 595.3 x 841.9)")
        texts = [(p.extract_text() or "") for p in reader.pages]
        empty = [i + 1 for i, t in enumerate(texts) if not t.strip()]
        add("non-empty-pages", True, not empty,
            "all pages have extractable text" if not empty else f"empty pages: {empty}")
        full = "\n".join(texts)
        add("title-present", True, bool(topic and topic[:40] in full),
            f"topic {'found' if topic and topic[:40] in full else 'MISSING'} in text")
        add("sources-section", True, "Sources" in full,
            "Sources heading present" if "Sources" in full else "Sources heading MISSING")
        urls = [l for l in full.split() if l.startswith("http")]
        add("source-links", True, len(urls) >= min_sources,
            f"{len(urls)} URL(s) embedded (want ≥{min_sources})")
        add("readability", True, len(full.split()) >= 100,
            f"{len(full.split())} words extracted")
    except Exception as e:
        add("parse", True, False, f"could not parse PDF: {e}")
    return findings
