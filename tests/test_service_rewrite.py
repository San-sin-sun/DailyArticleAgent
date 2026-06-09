from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from dailyarticleagent.digest import build_daily_digest, write_digest
from dailyarticleagent.models import ClassifiedPaper, Paper, PaperInsight
from dailyarticleagent.service import AgentService, AppPaths


def test_rewrite_digests_uses_stored_paper_insights(tmp_path) -> None:
    paths = AppPaths(
        config_path=Path("config/watch_profiles.yaml"),
        db_path=tmp_path / "articles.sqlite",
        content_dir=tmp_path / "content",
    )
    service = AgentService(paths=paths)
    try:
        profile = service.profile("ai_systems_example")
        paper = Paper(
            uid="p1",
            title="Benchmarking retrieval agents with reproducible software tasks",
            authors=("A. Author",),
            abstract="A platform combines task traces, retrieval corpora, and reproducible evaluation harnesses.",
            source="arxiv",
            source_kind="arxiv",
            published_at=date(2026, 6, 8),
            discovered_at=datetime(2026, 6, 8, tzinfo=UTC),
            url="http://arxiv.org/abs/2605.25697v1",
            raw_id="2605.25697v1",
        )
        classified = [
            ClassifiedPaper(
                paper=paper,
                profile_id=profile.id,
                relevance_score=78,
                novelty_score=20,
                evidence_score=40,
                total_score=78,
                reasons=("关键词命中: evaluation benchmark",),
                labels=("evaluation", "platform", "benchmark", "benchmarking"),
            )
        ]
        service.repo.save_papers([paper])
        service.repo.save_classifications(classified)

        old_digest = build_daily_digest(
            profile,
            classified,
            date(2026, 6, 8),
            date(2026, 6, 8),
            paths.content_dir,
        )
        write_digest(old_digest)
        service.repo.save_digest(old_digest)

        service.repo.save_paper_insights(
            [
                PaperInsight(
                    paper_uid="p1",
                    profile_id=profile.id,
                    chinese_summary="这篇论文搭建了检索语料、任务轨迹和可复现实验评测的联合平台。",
                    content_analysis=(
                        "内容性分析：重点是任务构造、检索证据选择、基线系统对齐，"
                        "以及评测流水线中的可重复运行。"
                    ),
                    critique=(
                        "内容性 judge：78 分偏低主要是频道关键词窄，不代表平台价值低；"
                        "真正风险在于数据泄漏、基线不足和跨任务泛化限制。"
                    ),
                    follow_up="检查数据泄漏控制、基线覆盖、统计显著性和跨项目复现实验。",
                    evidence_scope="stored arXiv abstract/PDF insight",
                    confidence="high",
                )
            ]
        )

        rewritten = service.rewrite_digests(profile_id=profile.id)
    finally:
        service.close()

    text = (paths.content_dir / "daily" / "2026-06-08" / f"{profile.id}.md").read_text(encoding="utf-8")
    assert rewritten == 1
    assert "内容性分析：重点是任务构造" in text
    assert "内容性 judge：78 分偏低" in text
    assert "未启用 LLM 阅读时" not in text
