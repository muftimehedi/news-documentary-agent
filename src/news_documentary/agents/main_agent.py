"""Main Deep Agent harness using official `create_deep_agent`.

Ownership:
- Deep Agent (this file): open-ended planning, research delegation, synthesis, progress.
- Outer LangGraph workflow (workflow/graph.py): explicit stage transitions, side effects,
  checkpoints, approval gate, publishing. It CALLS this agent for planning/research steps.
We do not duplicate the agent loop inside the graph.
"""
from __future__ import annotations

from pathlib import Path

from . import prompts
from ..tools.doc_tools import (
    save_artifact,
    rank_topics,
    extract_claims,
    check_claim_support,
    estimate_narration_timing,
    build_render_manifest,
    news_search,
)


def build_subagents():
    return [
        {"name": "researcher", "description": "Discover recent topics, collect primary reporting + metadata, rank candidates.",
         "system_prompt": prompts.RESEARCH_PROMPT, "tools": [news_search, save_artifact, rank_topics]},
        {"name": "fact-checker", "description": "Independently verify claims with retrieval; report verified/disputed/unresolved.",
         "system_prompt": prompts.FACTCHECK_PROMPT, "tools": [news_search, save_artifact, extract_claims, check_claim_support]},
        {"name": "scriptwriter", "description": "Write original narration (English default, Bengali supported) + scene plan grounded in verified claims.",
         "system_prompt": prompts.SCRIPT_PROMPT, "tools": [save_artifact, estimate_narration_timing]},
        {"name": "media-preparer", "description": "Prepare assets, speech, captions, render manifest via dedicated tools.",
         "system_prompt": prompts.MEDIA_PROMPT, "tools": [save_artifact, build_render_manifest, estimate_narration_timing]},
        {"name": "reviewer", "description": "Inspect factual consistency, subtitles, visuals, sourcing, technical quality.",
         "system_prompt": prompts.REVIEW_PROMPT, "tools": [save_artifact]},
    ]


def cost_guard_middleware(max_calls: int = 40):
    """Verified API: langchain.agents.middleware.wrap_tool_call decorator."""
    from langchain.agents.middleware import wrap_tool_call

    state = {"calls": 0, "cost": 0.0}

    @wrap_tool_call
    def _guard(request, handler):
        state["calls"] += 1
        if state["calls"] > max_calls:
            raise RuntimeError(f"Model/tool call budget exhausted ({max_calls})")
        name = (getattr(getattr(request, "tool_call", None), "name", None)
                or getattr(getattr(request, "tool", None), "name", None)
                or "unknown")
        print(f"[progress] tool={name} calls={state['calls']}")
        return handler(request)

    return _guard


def create_main_agent(settings, checkpointer=None, store=None, slim: bool = False):
    """Build the real Main Deep Agent. Fixture mode (no NEWS_MODEL) still builds the
    harness so delegation structure is exercised; live LLM calls only happen when configured.

    slim=True: minimal prompt for token-constrained tiers (e.g. Groq on_demand 8k TPM):
    same 5 subagents for delegation, but no skills/memory loading and one filesystem
    tool on the coordinator. Saves ~1k+ prompt tokens."""
    from deepagents import create_deep_agent

    raw = (getattr(settings, "news_model", "") or "").strip()
    if raw:
        model = raw
    else:
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        model = GenericFakeChatModel(messages=iter(["FIXTURE harness response (no live LLM configured)"]))
    skills_dir = str(Path(__file__).resolve().parents[3] / "skills")
    agents_md = str(Path(__file__).resolve().parents[3] / "AGENTS.md")
    kwargs: dict = dict(
        model=model,
        system_prompt=prompts.MAIN_PROMPT,
        tools=[news_search, save_artifact] if slim else [news_search, save_artifact, rank_topics, extract_claims, check_claim_support,
               estimate_narration_timing, build_render_manifest],
        subagents=build_subagents(),
        middleware=[cost_guard_middleware(getattr(settings, "max_model_calls", 40))],
        interrupt_on={"publish_to_youtube": True, "publish_to_facebook": True},
    )
    # Only pass skills/memory when the paths exist (documented params).
    # Skipped in slim mode to stay under tight TPM limits.
    if not slim and Path(skills_dir).exists():
        kwargs["skills"] = [skills_dir]
    if not slim and Path(agents_md).exists():
        kwargs["memory"] = [agents_md]
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if store is not None:
        kwargs["store"] = store
    return create_deep_agent(**kwargs)
