"""Model helper: reuse existing project config; empty NEWS_MODEL = fixture mode."""
from __future__ import annotations


def resolve_model_id(settings) -> str | None:
    mid = (getattr(settings, "news_model", "") or "").strip()
    return mid or None


def init_model(settings):
    """Return a LangChain chat model, or None in fixture mode (no keys needed)."""
    mid = resolve_model_id(settings)
    if not mid:
        return None
    from langchain.chat_models import init_chat_model

    return init_chat_model(mid)


def is_live(settings) -> bool:
    return resolve_model_id(settings) is not None


def export_keys_to_env(settings) -> None:
    """LangChain providers read credentials from os.environ; mirror Settings keys
    there (without overriding already-exported vars). Call at job entrypoints."""
    import os

    for env_name, val in (
        ("GROQ_API_KEY", getattr(settings, "groq_api_key", "")),
        ("TAVILY_API_KEY", getattr(settings, "tavily_api_key", "")),
        ("OPENAI_API_KEY", getattr(settings, "openai_api_key", "")),
        ("GOOGLE_API_KEY", getattr(settings, "google_api_key", "")),
        ("ANTHROPIC_API_KEY", getattr(settings, "anthropic_api_key", "")),
    ):
        if val and not os.environ.get(env_name):
            os.environ[env_name] = val
