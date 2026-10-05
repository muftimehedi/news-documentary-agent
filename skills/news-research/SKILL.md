---
name: news-research
description: Discover recent topics, collect primary reporting and source metadata, rank by recency/relevance/evidence/trend signal.
version: 1.0.0
---
# News research procedure
1. Search live (Tavily/RSS) for the 24h window (Asia/Dhaka). Never use model memory as evidence.
2. Record url, publisher, title, published/updated, retrieved_at, event_time, excerpt<=1000 chars.
3. Distinguish event time vs publish time; flag stale recirculated news.
4. Prefer primary sources; syndicated copies are not independent confirmation.
5. Trend signal = explained (independent publishers + window), not search rank.
6. Save research_notes.json in the job namespace; return candidates + refs.
