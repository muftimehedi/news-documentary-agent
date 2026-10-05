"""Typed state and artifacts. Single source of truth for the LangGraph state."""
from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict
from pydantic import BaseModel, Field
import operator


class Source(BaseModel):
    url: str
    publisher: str = ""
    title: str = ""
    published_at: str = ""
    updated_at: str = ""
    retrieved_at: str = ""
    event_time: str = ""
    excerpt: str = ""
    is_primary: bool = False
    fixture: bool = False


class TopicCandidate(BaseModel):
    topic: str
    summary: str = ""
    trend_signal: str = ""
    score: float = 0.0
    source_urls: list[str] = []


class Claim(BaseModel):
    id: str
    text: str
    kind: Literal["fact", "allegation", "opinion", "unknown"] = "fact"
    status: Literal["verified", "disputed", "unresolved"] = "unresolved"
    source_urls: list[str] = []
    notes: str = ""


class FactCheckReport(BaseModel):
    verified: list[Claim] = []
    disputed: list[Claim] = []
    unresolved: list[Claim] = []
    blocked: bool = False
    block_reason: str = ""


class Scene(BaseModel):
    index: int
    narration: str
    claim_ids: list[str] = []
    visual: str = ""
    on_screen_text: str = ""
    asset: str = ""
    duration_s: float = 5.0


class Script(BaseModel):
    title: str = ""
    narration_full: str = ""
    language: str = "bn"
    scenes: list[Scene] = []
    version: int = 1


class ReviewFinding(BaseModel):
    area: str
    checked: bool
    passed: bool
    detail: str = ""


class ReviewReport(BaseModel):
    passed: bool = False
    findings: list[ReviewFinding] = []
    needs_revision: str = ""


class PublishReceipt(BaseModel):
    destination: str
    remote_id: str = ""
    url: str = ""
    visibility: str = ""
    status: str = ""
    timestamp: str = ""
    fixture: bool = False


class JobState(TypedDict, total=False):
    job_id: str
    thread_id: str
    settings_snapshot: dict[str, Any]
    stage: str
    status: str
    topic: str
    sources: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    fact_report: dict[str, Any]
    script: dict[str, Any]
    scenes: list[dict[str, Any]]
    assets: dict[str, Any]
    artifacts: dict[str, str]
    review: dict[str, Any]
    approval: dict[str, Any]
    receipts: list[dict[str, Any]]
    cost_usd: float
    model_calls: int
    attempts: Annotated[int, operator.add]
    error: str
    log: Annotated[list[str], operator.add]
