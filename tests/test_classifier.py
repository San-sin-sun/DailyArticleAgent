from __future__ import annotations

from datetime import UTC, date, datetime

from dailyarticleagent.classifier import classify_all_papers, classify_papers
from dailyarticleagent.models import Paper, SourceConfig, WatchProfile


def test_classify_selects_relevant_ai_systems_paper() -> None:
    profile = WatchProfile(
        id="ai_systems_example",
        name="AI Systems Example",
        description="",
        language="zh-CN",
        max_items=3,
        keywords=("retrieval augmented generation", "agent evaluation"),
        exclude_keywords=("clinical trial",),
        sources=(SourceConfig(name="arxiv", kind="arxiv"),),
    )
    paper = Paper(
        uid="p1",
        title="An agent evaluation platform for retrieval augmented generation",
        authors=("A. Researcher",),
        abstract="We report a software agent evaluation with reproducible retrieval benchmarks.",
        source="arxiv",
        source_kind="arxiv",
        published_at=date(2026, 6, 1),
        discovered_at=datetime.now(UTC),
        url="https://arxiv.org/abs/1234.5678",
    )

    selected = classify_papers(profile, [paper])

    assert len(selected) == 1
    assert selected[0].paper.uid == "p1"
    assert selected[0].total_score > 50
    assert "agent-evaluation" in selected[0].labels


def test_classify_rejects_excluded_low_relevance_paper() -> None:
    profile = WatchProfile(
        id="ai_systems_example",
        name="AI Systems Example",
        description="",
        language="zh-CN",
        max_items=3,
        keywords=("retrieval agent",),
        exclude_keywords=("clinical trial",),
        sources=(SourceConfig(name="arxiv", kind="arxiv"),),
    )
    paper = Paper(
        uid="p2",
        title="Clinical trial prediction scenario",
        authors=(),
        abstract="A clinical trial prediction study.",
        source="arxiv",
        source_kind="arxiv",
        published_at=date(2026, 6, 1),
        discovered_at=datetime.now(UTC),
        url="https://example.test",
    )

    assert classify_papers(profile, [paper]) == []


def test_classify_applies_feedback_adjustment() -> None:
    profile = WatchProfile(
        id="ai_systems_example",
        name="AI Systems Example",
        description="",
        language="zh-CN",
        max_items=3,
        keywords=("retrieval agent",),
        exclude_keywords=(),
        sources=(SourceConfig(name="arxiv", kind="arxiv"),),
    )
    paper = Paper(
        uid="p3",
        title="Retrieval agent benchmark",
        authors=(),
        abstract="A retrieval agent benchmark.",
        source="arxiv",
        source_kind="arxiv",
        published_at=date(2026, 6, 1),
        discovered_at=datetime.now(UTC),
        url="https://example.test",
    )

    baseline = classify_all_papers(profile, [paper])[0]
    adjusted = classify_all_papers(profile, [paper], feedback_adjustments={"p3": 15})[0]

    assert adjusted.total_score == baseline.total_score + 15
    assert "人工反馈调分: +15" in adjusted.reasons
