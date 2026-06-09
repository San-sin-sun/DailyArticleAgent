from __future__ import annotations

from datetime import UTC, date, datetime

from dailyarticleagent.digest import build_daily_digest, write_digest
from dailyarticleagent.models import ClassifiedPaper, Paper, SourceConfig, WatchProfile
from dailyarticleagent.reader import PaperReading


class FakeLlm:
    def summarize(self, system: str, user: str) -> str:
        assert "Paper analysis" in user
        return "今日重点是诊断论文 [1]，但需要核查实验标定和噪声来源。"

    def summarize_json(self, system: str, user: str) -> dict:
        assert "Additional reading evidence" in user
        return {
            "chinese_summary": "该文提出一种可复现实验评测框架，用于检索增强 agent 的任务表现评估。",
            "content_analysis": (
                "从正文片段看，文章的技术核心不是泛泛的 benchmark，而是把任务评测器、"
                "检索证据窗口和软件 agent 运行条件绑定起来。"
            ),
            "critique": "目前证据仍缺少跨 run 重复性、基线覆盖和误差分解，不应只凭摘要判断性能成熟。",
            "follow_up": "后续应检查数据集覆盖度、基线方法、统计显著性、误差条，以及是否在真实软件项目中复现。",
            "evidence_scope": "source metadata plus test excerpt",
            "confidence": "high",
        }


class FakeReader:
    def read(self, paper: Paper) -> PaperReading:
        return PaperReading(
            "The retrieval benchmark is calibrated against baseline systems and tested on repeated runs.",
            "source metadata plus test excerpt",
            reading_path="content/readings/p1.txt",
            source_path="content/readings/p1.pdf",
        )


def test_write_daily_digest(tmp_path) -> None:
    profile = WatchProfile(
        id="ml_systems",
        name="ML Systems",
        description="",
        language="zh-CN",
        max_items=3,
        keywords=("benchmark",),
        exclude_keywords=(),
        sources=(SourceConfig(name="rss", kind="rss"),),
    )
    paper = Paper(
        uid="p1",
        title="Benchmark suite for retrieval agents",
        authors=("A. Author",),
        abstract="A compact benchmark measures retrieval quality and tool-use reliability.",
        source="acm",
        source_kind="crossref",
        published_at=date(2026, 6, 1),
        discovered_at=datetime.now(UTC),
        url="https://doi.org/10.0000/test",
        doi="10.0000/test",
        journal="ACM Transactions on Software Engineering and Methodology",
    )
    item = ClassifiedPaper(
        paper=paper,
        profile_id=profile.id,
        relevance_score=80,
        novelty_score=30,
        evidence_score=30,
        total_score=90,
        reasons=("关键词命中: benchmark",),
        labels=("benchmark",),
    )

    digest = build_daily_digest(profile, [item], date(2026, 6, 1), date(2026, 6, 8), tmp_path)
    write_digest(digest)

    text = (tmp_path / "daily" / "2026-06-08" / "ml_systems.md").read_text(encoding="utf-8")
    assert "Benchmark suite for retrieval agents" in text
    assert "Executive Summary" in text
    assert "中文摘要" in text
    assert "不足与待改进" in text


def test_llm_paper_insight_is_written_to_digest(tmp_path) -> None:
    profile = WatchProfile(
        id="ml_systems",
        name="ML Systems",
        description="",
        language="zh-CN",
        max_items=3,
        keywords=("benchmark",),
        exclude_keywords=(),
        sources=(SourceConfig(name="rss", kind="rss"),),
    )
    item = ClassifiedPaper(
        paper=Paper(
            uid="p1",
            title="Benchmark suite for retrieval agents",
            authors=("A. Author",),
            abstract="A compact benchmark measures retrieval quality and tool-use reliability.",
            source="acm",
            source_kind="crossref",
            published_at=date(2026, 6, 1),
            discovered_at=datetime.now(UTC),
            url="https://doi.org/10.0000/test",
            doi="10.0000/test",
            journal="ACM Transactions on Software Engineering and Methodology",
        ),
        profile_id=profile.id,
        relevance_score=80,
        novelty_score=30,
        evidence_score=30,
        total_score=90,
        reasons=("关键词命中: benchmark",),
        labels=("benchmark",),
    )

    digest = build_daily_digest(
        profile,
        [item],
        date(2026, 6, 1),
        date(2026, 6, 8),
        tmp_path,
        llm=FakeLlm(),
        reader=FakeReader(),
    )
    write_digest(digest)

    text = (tmp_path / "daily" / "2026-06-08" / "ml_systems.md").read_text(encoding="utf-8")
    assert "可复现实验评测框架" in text
    assert "跨 run 重复性、基线覆盖和误差分解" in text
    assert "source metadata plus test excerpt；置信度：high" in text
    assert digest.paper_insights[0].profile_id == profile.id
    assert digest.paper_insights[0].reading_path == "content/readings/p1.txt"
