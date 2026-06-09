from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from dailyarticleagent.models import (
    Digest,
    DigestPeriod,
    FeedbackRating,
    PaperFeedback,
    PaperInsight,
    SourceConfig,
    WatchProfile,
)
from dailyarticleagent.storage import Repository


def test_digest_upsert_deduplicates_same_markdown_path(tmp_path) -> None:
    repo = Repository(tmp_path / "articles.sqlite")
    profile = WatchProfile(
        id="ai_systems_example",
        name="AI Systems Example",
        description="",
        language="zh-CN",
        max_items=10,
        keywords=(),
        exclude_keywords=(),
        sources=(SourceConfig(name="arxiv", kind="arxiv"),),
    )
    digest = Digest(
        profile=profile,
        period=DigestPeriod.DAILY,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 8),
        generated_at=datetime.now(UTC),
        papers=(),
        summary="first",
        markdown_path="content/daily/2026-06-08/ai_systems_example.md",
        title="Daily",
    )

    repo.save_digest(digest)
    repo.save_digest(digest)
    rows = repo.list_digests()
    repo.close()

    assert len(rows) == 1
    assert rows[0]["summary"] == "first"


def test_digest_upsert_normalizes_windows_paths(tmp_path) -> None:
    repo = Repository(tmp_path / "articles.sqlite")
    profile = _profile()
    base = Digest(
        profile=profile,
        period=DigestPeriod.WEEKLY,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 7),
        generated_at=datetime.now(UTC),
        papers=(),
        summary="first",
        markdown_path="content\\weekly\\2026-W23\\ai_systems_example.md",
        title="Weekly",
    )
    same = Digest(
        profile=profile,
        period=DigestPeriod.WEEKLY,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 7),
        generated_at=datetime.now(UTC),
        papers=(),
        summary="second",
        markdown_path="content/weekly/2026-W23/ai_systems_example.md",
        title="Weekly",
    )

    repo.save_digest(base)
    repo.save_digest(same)
    rows = repo.list_digests()
    repo.close()

    assert len(rows) == 1
    assert rows[0]["summary"] == "second"
    assert rows[0]["markdown_path"] == "content/weekly/2026-W23/ai_systems_example.md"


def test_seen_profile_uids_tracks_classified_papers(tmp_path) -> None:
    repo = Repository(tmp_path / "articles.sqlite")
    profile = _profile()
    paper = _paper("p1")
    from dailyarticleagent.classifier import classify_all_papers

    repo.save_papers([paper])
    repo.save_classifications(classify_all_papers(profile, [paper]))

    assert repo.seen_profile_uids(profile.id, ["p1", "p2"]) == {"p1"}
    repo.close()


def test_repository_migrates_old_digest_unique_index(tmp_path) -> None:
    db_path = tmp_path / "articles.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL,
            period TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            markdown_path TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_digests_unique_period
        ON digests(profile_id, period, start_date, end_date, markdown_path);
        """
    )
    conn.close()

    repo = Repository(db_path)
    digest = Digest(
        profile=_profile(),
        period=DigestPeriod.DAILY,
        start_date=date(2026, 6, 9),
        end_date=date(2026, 6, 9),
        generated_at=datetime.now(UTC),
        papers=(),
        summary="migrated",
        markdown_path="content/daily/2026-06-09/ai_systems_example.md",
        title="Daily",
    )

    repo.save_digest(digest)
    repo.save_digest(digest)
    rows = repo.list_digests()
    repo.close()

    assert len(rows) == 1
    assert rows[0]["summary"] == "migrated"


def test_save_digest_persists_paper_insights_for_api(tmp_path) -> None:
    repo = Repository(tmp_path / "articles.sqlite")
    profile = _profile()
    paper = _paper("p1")
    repo.save_papers([paper])
    digest = Digest(
        profile=profile,
        period=DigestPeriod.DAILY,
        start_date=date(2026, 6, 9),
        end_date=date(2026, 6, 9),
        generated_at=datetime.now(UTC),
        papers=(),
        summary="summary",
        markdown_path="content/daily/2026-06-09/ai_systems_example.md",
        title="Daily",
        paper_insights=(
            PaperInsight(
                paper_uid="p1",
                profile_id=profile.id,
                chinese_summary="中文总结",
                content_analysis="内容 insight",
                critique="这个工作的证据还不够强。",
                follow_up="检查标定和误差条。",
                evidence_scope="source metadata plus local excerpt",
                reading_path="content/readings/p1.txt",
                source_path="content/readings/p1.pdf",
                confidence="medium",
            ),
        ),
    )
    from dailyarticleagent.classifier import classify_all_papers

    repo.save_classifications(classify_all_papers(profile, [paper]))
    repo.save_digest(digest)

    rows = repo.list_papers(profile_id=profile.id)
    repo.close()

    assert rows[0]["insight"]["chinese_summary"] == "中文总结"
    assert rows[0]["insight"]["critique"] == "这个工作的证据还不够强。"
    assert rows[0]["insight"]["reading_path"] == "content/readings/p1.txt"


def test_selected_classifications_can_filter_missing_insights(tmp_path) -> None:
    repo = Repository(tmp_path / "articles.sqlite")
    profile = _profile()
    paper = _paper("p1")
    repo.save_papers([paper])

    from dailyarticleagent.classifier import classify_all_papers

    repo.save_classifications(classify_all_papers(profile, [paper]))

    assert len(repo.selected_classifications(profile, limit=10, missing_insights_only=True)) == 1
    repo.save_paper_insights(
        [
            PaperInsight(
                paper_uid="p1",
                profile_id=profile.id,
                chinese_summary="中文总结",
                content_analysis="内容 insight",
                critique="judge",
                follow_up="follow",
                evidence_scope="metadata",
                confidence="medium",
            )
        ]
    )
    assert repo.selected_classifications(profile, limit=10, missing_insights_only=True) == []
    repo.close()


def test_save_paper_insights_commits_standalone_writes(tmp_path) -> None:
    db_path = tmp_path / "articles.sqlite"
    profile = _profile()
    paper = _paper("p1")

    repo = Repository(db_path)
    repo.save_papers([paper])

    from dailyarticleagent.classifier import classify_all_papers

    repo.save_classifications(classify_all_papers(profile, [paper]))
    repo.save_paper_insights(
        [
            PaperInsight(
                paper_uid="p1",
                profile_id=profile.id,
                chinese_summary="重新打开后仍然存在",
                content_analysis="这是对论文内容的分析。",
                critique="证据链需要继续核查。",
                follow_up="追踪实验参数和误差来源。",
                evidence_scope="metadata plus llm reading",
                confidence="medium",
            )
        ]
    )
    repo.close()

    reopened = Repository(db_path)
    rows = reopened.list_papers(profile_id=profile.id)
    reopened.close()

    assert rows[0]["insight"]["chinese_summary"] == "重新打开后仍然存在"
    assert rows[0]["insight"]["content_analysis"] == "这是对论文内容的分析。"


def test_paper_insights_for_profile_returns_requested_rows(tmp_path) -> None:
    repo = Repository(tmp_path / "articles.sqlite")
    profile = _profile()
    paper = _paper("p1")
    repo.save_papers([paper])

    from dailyarticleagent.classifier import classify_all_papers

    repo.save_classifications(classify_all_papers(profile, [paper]))
    repo.save_paper_insights(
        [
            PaperInsight(
                paper_uid="p1",
                profile_id=profile.id,
                chinese_summary="中文总结",
                content_analysis="stored content analysis",
                critique="stored critique",
                follow_up="stored follow up",
                evidence_scope="stored evidence",
                confidence="high",
            )
        ]
    )

    insights = repo.paper_insights_for_profile(profile.id, ["p1", "missing"])
    repo.close()

    assert len(insights) == 1
    assert insights[0].paper_uid == "p1"
    assert insights[0].content_analysis == "stored content analysis"


def test_feedback_adjustments_and_latest_rating_are_available(tmp_path) -> None:
    repo = Repository(tmp_path / "articles.sqlite")
    profile = _profile()
    paper = _paper("p1")
    repo.save_papers([paper])

    from dailyarticleagent.classifier import classify_all_papers

    repo.save_classifications(classify_all_papers(profile, [paper]))
    repo.save_feedback(PaperFeedback(paper_uid="p1", profile_id=profile.id, rating=FeedbackRating.UP))
    repo.save_feedback(PaperFeedback(paper_uid="p1", profile_id=profile.id, rating=FeedbackRating.SAVE))

    rows = repo.list_papers(profile_id=profile.id)
    adjustments = repo.feedback_adjustments(profile.id)
    repo.close()

    assert adjustments["p1"] == 23
    assert rows[0]["feedback_rating"] == FeedbackRating.SAVE.value


def _profile() -> WatchProfile:
    return WatchProfile(
        id="ai_systems_example",
        name="AI Systems Example",
        description="",
        language="zh-CN",
        max_items=10,
        keywords=("retrieval agent",),
        exclude_keywords=(),
        sources=(SourceConfig(name="arxiv", kind="arxiv"),),
    )


def _paper(uid: str):
    from dailyarticleagent.models import Paper

    return Paper(
        uid=uid,
        title="Retrieval agent evaluation study",
        authors=(),
        abstract="A retrieval agent evaluation study.",
        source="arxiv",
        source_kind="arxiv",
        published_at=date(2026, 6, 1),
        discovered_at=datetime.now(UTC),
        url="https://example.test",
    )
