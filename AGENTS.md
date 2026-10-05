# AGENTS.md — durable operating instructions for this channel/repo

- Style: plain-English explanations; English identifiers in code.
- Main Agent plans + delegates via `task` tool; subagents get narrow prompts, minimal context, typed JSON deliverables.
- Deterministic work (FFmpeg render, YouTube upload, sqlite writes) lives in tools/workers, never as LLM subagents.
- Research must use retrieval (RSS/Tavily), never model memory. Record full source metadata.
- Fact-check independently re-fetches; block (don't invent) when unverifiable.
- Generated visuals are labeled synthetic; never present them as real footage.
- Fixture mode outputs are labeled `fixture` everywhere; never masquerade as live.
- Publish only with bound approval (video hash + script version + destinations) or auto-policy after passed review.
- Keep checkpoints (short-term resume), long-term store (preferences/history), and media files separate.
- This file holds stable instructions, not a log of every conversation.
