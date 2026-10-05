"""News search adapters behind one interface. Never use model memory as evidence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures"


class SearchResult(dict):
    pass


class NewsSearchAdapter(Protocol):
    name: str
    def search(self, query: str, max_results: int = 8) -> list[dict]: ...
    def top_news(self, max_results: int = 8) -> list[dict]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FixtureSearchAdapter:
    """Clearly labeled offline news fixture. Never masquerades as live research."""

    name = "fixture"

    def _load(self) -> list[dict]:
        fp = FIXTURE_DIR / "sample_news.json"
        items = json.loads(fp.read_text(encoding="utf-8"))
        out = []
        for it in items:
            out.append({**it, "retrieved_at": _now(), "fixture": True})
        return out

    def search(self, query: str, max_results: int = 8) -> list[dict]:
        q = query.lower()
        items = self._load()
        ranked = sorted(items, key=lambda d: (q in (d.get("title", "") + d.get("excerpt", "")).lower()), reverse=True)
        return ranked[:max_results]

    def top_news(self, max_results: int = 8) -> list[dict]:
        return self._load()[:max_results]


class RssSearchAdapter:
    """Live RSS reader (Google News RSS + BBC). No API key needed."""

    name = "rss"

    FEEDS = [
        "https://news.google.com/rss?hl=en&gl=BD&ceid=BD:en",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
    ]

    def _fetch_feed(self, url: str, max_items: int) -> list[dict]:
        import feedparser

        parsed = feedparser.parse(url)
        out = []
        for e in parsed.entries[:max_items]:
            out.append(
                {
                    "url": getattr(e, "link", ""),
                    "publisher": parsed.feed.get("title", url),
                    "title": getattr(e, "title", ""),
                    "published_at": getattr(e, "published", ""),
                    "updated_at": getattr(e, "updated", ""),
                    "retrieved_at": _now(),
                    "event_time": "",
                    "excerpt": getattr(e, "summary", "")[:800],
                    "is_primary": False,
                    "fixture": False,
                }
            )
        return out

    def search(self, query: str, max_results: int = 8) -> list[dict]:
        import urllib.parse

        q = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={q}%20when:1d&hl=en&gl=BD&ceid=BD:en"
        try:
            return self._fetch_feed(url, max_results)
        except Exception:
            return []

    def top_news(self, max_results: int = 8) -> list[dict]:
        out: list[dict] = []
        for f in self.FEEDS:
            try:
                out.extend(self._fetch_feed(f, max_results // len(self.FEEDS) + 2))
            except Exception:
                continue
        return out[:max_results]


class TavilySearchAdapter:
    """Live Tavily news search. Requires TAVILY_API_KEY."""

    name = "tavily"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("TAVILY_API_KEY missing")
        from tavily import TavilyClient

        self.client = TavilyClient(api_key=api_key)

    def _norm(self, r: dict) -> dict:
        from urllib.parse import urlparse

        url = r.get("url", "")
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = ""
        return {
            "url": url,
            "publisher": r.get("source") or r.get("author") or domain,
            "title": r.get("title", ""),
            "published_at": r.get("published_date", ""),
            "updated_at": "",
            "retrieved_at": _now(),
            "event_time": "",
            "excerpt": (r.get("content", "") or "")[:1000],
            "is_primary": False,
            "fixture": False,
        }

    def search(self, query: str, max_results: int = 8) -> list[dict]:
        res = self.client.search(query, max_results=max_results, topic="news", time_range="day", include_answer=False)
        return [self._norm(r) for r in res.get("results", [])]

    def top_news(self, max_results: int = 8) -> list[dict]:
        return self.search("Bangladesh breaking news", max_results)


def get_search_adapter(settings) -> NewsSearchAdapter:
    if getattr(settings, "tavily_api_key", ""):
        try:
            return TavilySearchAdapter(settings.tavily_api_key)
        except Exception:
            pass
    # Prefer RSS live; fall back to fixture only when explicitly fixture or offline.
    return RssSearchAdapter()
