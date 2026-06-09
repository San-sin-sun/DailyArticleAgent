from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class DigestPeriod(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class PaperStatus(StrEnum):
    NEW = "new"
    SELECTED = "selected"
    REJECTED = "rejected"


class RunAction(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    REANALYZE = "reanalyze"
    REWRITE_DIGESTS = "rewrite_digests"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class FeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"
    SAVE = "save"
    SKIP = "skip"


@dataclass(frozen=True)
class SourceConfig:
    name: str
    kind: str
    query: str | None = None
    issn: str | None = None
    url: str | None = None
    limit: int = 25


@dataclass(frozen=True)
class WatchProfile:
    id: str
    name: str
    description: str
    language: str
    max_items: int
    keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]
    sources: tuple[SourceConfig, ...]
    broad_discovery: bool = False


@dataclass(frozen=True)
class Paper:
    uid: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    source: str
    source_kind: str
    published_at: date | None
    discovered_at: datetime
    url: str
    doi: str | None = None
    journal: str | None = None
    raw_id: str | None = None

    @property
    def citation_id(self) -> str:
        if self.doi:
            return self.doi
        if self.raw_id:
            return self.raw_id
        return self.uid


@dataclass(frozen=True)
class ClassifiedPaper:
    paper: Paper
    profile_id: str
    relevance_score: int
    novelty_score: int
    evidence_score: int
    total_score: int
    reasons: tuple[str, ...]
    labels: tuple[str, ...]
    status: PaperStatus = PaperStatus.SELECTED


@dataclass(frozen=True)
class PaperInsight:
    paper_uid: str
    profile_id: str
    chinese_summary: str
    content_analysis: str
    critique: str
    follow_up: str
    evidence_scope: str
    reading_path: str | None = None
    source_path: str | None = None
    confidence: str = "medium"


@dataclass(frozen=True)
class Digest:
    profile: WatchProfile
    period: DigestPeriod
    start_date: date
    end_date: date
    generated_at: datetime
    papers: tuple[ClassifiedPaper, ...]
    summary: str
    markdown_path: str
    paper_insights: tuple[PaperInsight, ...] = field(default_factory=tuple)
    title: str = field(default="")


@dataclass(frozen=True)
class AgentRun:
    id: int | None
    action: RunAction
    status: RunStatus
    profile_id: str
    started_at: datetime
    finished_at: datetime | None = None
    attempts: int = 1
    parent_run_id: int | None = None
    options_json: str = "{}"
    result_count: int = 0
    error: str = ""


@dataclass(frozen=True)
class PaperFeedback:
    paper_uid: str
    profile_id: str
    rating: FeedbackRating
    note: str = ""
    created_at: datetime | None = None
