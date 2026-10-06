"""Python mirror of packages/contracts v1 (job IDs + artifact refs, no large media)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1"

JobStatus = Literal[
    "queued", "leased", "running", "awaiting-approval", "approved",
    "publishing", "published", "failed", "cancelled",
    "blocked-no-evidence", "reviewed-failed", "done",
]
JobStage = Literal[
    "discover", "choose_topic", "research", "fact_check", "script",
    "prepare_media", "render", "review", "approval", "publish",
    "record_result", "done",
]

READABLE_EVENTS = (
    "research-started",
    "fact-check-completed",
    "script-ready",
    "generating-narration",
    "rendering-video",
    "video-ready",
    "upload-completed",
)


class ProductionSettings(BaseModel):
    topic: str = ""
    language: str = "en"
    duration_seconds: float = 75
    aspect_ratio: Literal["vertical", "horizontal"] = "vertical"
    narration_style: str = "neutral"
    tts_provider: Literal["fixture", "gtts"] = "fixture"
    video_provider: Literal["stills", "veo"] = "stills"
    veo_model: str = "veo-3.1-generate-preview"


class ProgressEvent(BaseModel):
    job_id: str
    kind: str
    message: str
    stage: str = ""
    status: str = ""
    data: dict = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    name: str
    path: str
    content_type: str = ""
    size_bytes: int = 0
    sha256: str = ""


# ------------------------------- v2 (doc scope) -------------------------------
CONTRACT_V2 = "2"

PLATFORM_LIMITS_V2 = {"x": 280, "facebook": 2000, "hikmah": 20000, "youtube": 5000}

TEXT_POST_DISABLED_V2 = {
    "youtube": "YouTube Data API v3 has no text/community-post endpoint "
               "(video upload and comments only). Use the generated title/description manually."
}


class SocialPostV2(BaseModel):
    text: str = ""
    title: str = ""
    description: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    chars: int = 0
    connect_post: bool = True
    note: str = ""
