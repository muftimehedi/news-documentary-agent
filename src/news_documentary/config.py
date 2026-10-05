"""Central settings. All tunables live here; env overrides file defaults."""
from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    news_model: str = Field(default="", description="LangChain model id 'provider:model'. Empty = fixture/deterministic mode.")
    tavily_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""

    tts_provider: str = "fixture"  # fixture | gtts
    narration_lang: str = "bn"
    doc_duration_seconds: int = 75
    video_aspect: str = "vertical"  # vertical | horizontal

    timezone: str = "Asia/Dhaka"
    news_window_hours: int = 24

    publish_policy: str = "manual"  # manual | auto
    youtube_visibility: str = "unlisted"  # unlisted | private | public
    youtube_client_secrets: str = ""
    youtube_token_file: str = "data/youtube_token.json"
    youtube_publish_mode: str = "fixture"  # fixture | real

    job_root: str = "data/jobs"
    db_path: str = "data/newsdoc.sqlite"

    max_cost_usd: float = 5.0
    max_model_calls: int = 40
    max_retries: int = 2

    @property
    def dimensions(self) -> tuple[int, int]:
        return (1080, 1920) if self.video_aspect == "vertical" else (1920, 1080)


def get_settings() -> Settings:
    return Settings()


def job_dir(job_root: str | Path, job_id: str) -> Path:
    p = Path(job_root) / job_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_join(base: Path, *parts: str) -> Path:
    """Prevent path traversal: resolved path must stay under base."""
    target = (base / Path(*parts)).resolve()
    base_r = base.resolve()
    if target != base_r and base_r not in target.parents:
        raise ValueError(f"Unsafe path: {target} escapes {base_r}")
    return target
