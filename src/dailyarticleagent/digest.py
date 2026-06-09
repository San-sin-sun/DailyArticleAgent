from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from jinja2 import Environment

from .llm import LlmClient
from .models import ClassifiedPaper, Digest, DigestPeriod, Paper, PaperInsight, WatchProfile
from .reader import PaperReader, PaperReading
from .text import clean_text, first_sentence

LOGGER = logging.getLogger(__name__)

MD_TEMPLATE = """# {{ title }}

- Profile: {{ profile.name }} (`{{ profile.id }}`)
- Period: {{ start_date }} to {{ end_date }}
- Generated: {{ generated_at }}
- Papers selected: {{ papers|length }}

## Executive Summary

{{ summary }}

## Papers
{% for item in papers %}

### {{ loop.index }}. {{ item.paper.title }}

- Score: {{ item.total_score }} / 100
- Labels: {{ item.labels|join(", ") }}
- Source: {{ item.paper.journal or item.paper.source }}
{% if item.paper.published_at %}- Published: {{ item.paper.published_at }}{% endif %}
- Authors: {{ item.paper.authors|join(", ") if item.paper.authors else "Unknown" }}
- Link: {{ item.paper.url }}
{% if item.paper.doi %}- DOI: {{ item.paper.doi }}{% endif %}

#### 中文摘要

{{ insight(item).chinese_summary }}

#### 详细分析

{{ insight(item).content_analysis }}

#### 不足与待改进

{{ insight(item).critique }}

#### 后续跟进

{{ insight(item).follow_up }}

#### 阅读证据范围

{{ insight(item).evidence_scope }}；置信度：{{ insight(item).confidence }}

#### 原始摘要证据

> {{ item.paper.abstract or "No abstract available from source metadata." }}
{% endfor %}

## Source Notes

This digest keeps source links, DOI/arXiv ids, and the abstract evidence used for ranking.
"""


class ReadingProvider(Protocol):
    def read(self, paper: Paper) -> PaperReading:
        ...


def build_daily_digest(
    profile: WatchProfile,
    papers: list[ClassifiedPaper],
    start: date,
    end: date,
    content_dir: Path,
    llm: LlmClient | None = None,
    reader: ReadingProvider | None = None,
    stored_insights: list[PaperInsight] | None = None,
) -> Digest:
    title = f"{profile.name} Daily Digest - {end.isoformat()}"
    insights = (
        stored_insights
        if stored_insights is not None
        else _paper_insights(profile, papers, llm, reader, content_dir)
    )
    summary = _llm_or_fallback(profile, DigestPeriod.DAILY, papers, insights, start, end, llm)
    path = content_dir / "daily" / end.isoformat() / f"{profile.id}.md"
    return _render_digest(profile, DigestPeriod.DAILY, papers, insights, start, end, title, summary, path)


def build_weekly_digest(
    profile: WatchProfile,
    papers: list[ClassifiedPaper],
    start: date,
    end: date,
    content_dir: Path,
    llm: LlmClient | None = None,
    reader: ReadingProvider | None = None,
    stored_insights: list[PaperInsight] | None = None,
) -> Digest:
    iso_year, iso_week, _ = end.isocalendar()
    title = f"{profile.name} Weekly Digest - {iso_year}-W{iso_week:02d}"
    insights = (
        stored_insights
        if stored_insights is not None
        else _paper_insights(profile, papers, llm, reader, content_dir)
    )
    summary = _llm_or_fallback(profile, DigestPeriod.WEEKLY, papers, insights, start, end, llm)
    path = content_dir / "weekly" / f"{iso_year}-W{iso_week:02d}" / f"{profile.id}.md"
    return _render_digest(profile, DigestPeriod.WEEKLY, papers, insights, start, end, title, summary, path)


def write_digest(digest: Digest) -> None:
    path = Path(digest.markdown_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    env = Environment(autoescape=False)
    template = env.from_string(MD_TEMPLATE)
    text = template.render(
        title=digest.title,
        profile=digest.profile,
        start_date=digest.start_date.isoformat(),
        end_date=digest.end_date.isoformat(),
        generated_at=digest.generated_at.isoformat(),
        papers=digest.papers,
        summary=digest.summary,
        insight=_insight_lookup(digest),
    )
    path.write_text(text, encoding="utf-8")


def _render_digest(
    profile: WatchProfile,
    period: DigestPeriod,
    papers: list[ClassifiedPaper],
    insights: list[PaperInsight],
    start: date,
    end: date,
    title: str,
    summary: str,
    path: Path,
) -> Digest:
    return Digest(
        profile=profile,
        period=period,
        start_date=start,
        end_date=end,
        generated_at=datetime.now(UTC),
        papers=tuple(papers),
        summary=summary,
        markdown_path=str(path),
        paper_insights=tuple(insights),
        title=title,
    )


def _llm_or_fallback(
    profile: WatchProfile,
    period: DigestPeriod,
    papers: list[ClassifiedPaper],
    insights: list[PaperInsight],
    start: date,
    end: date,
    llm: LlmClient | None,
) -> str:
    if llm:
        try:
            result = llm.summarize(
                (
                    "You write concise Chinese scientific literature intelligence. "
                    "Never invent claims without cited paper evidence."
                ),
                _summary_prompt(profile, period, papers, insights, start, end),
            )
            if result:
                return result
        except Exception as exc:
            LOGGER.warning("LLM digest summary failed; using deterministic fallback: %s", exc)
    return _fallback_summary(profile, period, papers, insights)


def _summary_prompt(
    profile: WatchProfile,
    period: DigestPeriod,
    papers: list[ClassifiedPaper],
    insights: list[PaperInsight],
    start: date,
    end: date,
) -> str:
    insight_by_uid = {insight.paper_uid: insight for insight in insights}
    rows = []
    for idx, item in enumerate(papers, 1):
        paper = item.paper
        insight = insight_by_uid.get(paper.uid)
        rows.append(
            f"{idx}. {paper.title}\n"
            f"Source: {paper.journal or paper.source}; "
            f"Date: {paper.published_at}; Score: {item.total_score}\n"
            f"Labels: {', '.join(item.labels)}\n"
            f"Paper analysis: {insight.content_analysis if insight else first_sentence(paper.abstract, 420)}\n"
            f"Critique: {insight.critique if insight else '未生成逐篇分析。'}\n"
            f"Link: {paper.url}\n"
        )
    return (
        f"Profile: {profile.name}\nPeriod: {period.value}, {start} to {end}\n"
        "Write Chinese Markdown with: 1) major trends, 2) key papers, 3) why it matters, "
        "4) limitations/weaknesses, 5) possible follow-up reading. "
        "Do not hide weak papers. Cite paper numbers like [1].\n\n"
        + "\n".join(rows)
    )


def _fallback_summary(
    profile: WatchProfile,
    period: DigestPeriod,
    papers: list[ClassifiedPaper],
    insights: list[PaperInsight] | None = None,
) -> str:
    if not papers:
        return "没有发现足够相关的新文献。建议保留该空档记录，避免以后误以为该频道当天没有运行。"
    insight_by_uid = {insight.paper_uid: insight for insight in insights or ()}
    labels = Counter(label for item in papers for label in item.labels)
    top_labels = ", ".join(label for label, _ in labels.most_common(5))
    top = papers[0]
    top_insight = insight_by_uid.get(top.paper.uid)
    cadence = "本周" if period == DigestPeriod.WEEKLY else "今日"
    lines = [
        (
            f"{cadence}为 `{profile.name}` 选出 {len(papers)} 篇文献。"
            f"主要主题集中在 {top_labels or '未分类主题'}。"
        ),
    ]
    if top_insight:
        lines.append(
            f"最高优先级文献是《{top.paper.title}》，评分 {top.total_score}/100。"
            f"内容上，{first_sentence(top_insight.content_analysis, 700)}"
        )
        lines.append(f"需要注意的是，{first_sentence(top_insight.critique, 700)}")
    else:
        lines.append(
            f"最高优先级文献是《{top.paper.title}》，评分 {top.total_score}/100，"
            f"入选依据是：{'; '.join(top.reasons[:2])}。"
        )
    if profile.broad_discovery:
        lines.append("该频道采用宽发现模式，允许非聚变但可能迁移到诊断、反演、控制或代理建模的机器学习方法进入列表。")
    weak = [item for item in papers if item.total_score < 80]
    if weak:
        lines.append(
            "需要谨慎阅读的条目包括："
            + "；".join(f"《{item.paper.title}》({item.total_score}/100)" for item in weak[:3])
            + "。这些论文可能相关性较窄、摘要证据不足，或更适合作为背景材料。"
        )
    return "\n\n".join(lines)


def _paper_insights(
    profile: WatchProfile,
    papers: list[ClassifiedPaper],
    llm: LlmClient | None,
    reader: ReadingProvider | None,
    content_dir: Path,
) -> list[PaperInsight]:
    local_pdf_dir = os.getenv("DAA_LOCAL_PDF_DIR", "").strip()
    active_reader = reader or (
        PaperReader(
            readings_dir=content_dir / "readings",
            local_pdf_dir=Path(local_pdf_dir).expanduser() if local_pdf_dir else None,
        )
        if llm
        else None
    )
    return [_paper_insight(profile, item, llm, active_reader) for item in papers]


def analyze_paper(
    profile: WatchProfile,
    item: ClassifiedPaper,
    llm: LlmClient | None,
    reader: ReadingProvider | None,
) -> PaperInsight:
    return _paper_insight(profile, item, llm, reader)


def _paper_insight(
    profile: WatchProfile,
    item: ClassifiedPaper,
    llm: LlmClient | None,
    reader: ReadingProvider | None,
) -> PaperInsight:
    reading = reader.read(item.paper) if reader else PaperReading("", "source metadata only; LLM reading disabled")
    if llm:
        try:
            data = llm.summarize_json(
                (
                    "You are a critical scientific reading agent. Return one JSON object only. "
                    "Base every claim on the provided paper evidence. Do not flatter weak papers."
                ),
                _paper_prompt(profile, item, reading),
            )
            if data:
                return PaperInsight(
                    paper_uid=item.paper.uid,
                    profile_id=profile.id,
                    chinese_summary=_json_text(data, "chinese_summary", _paper_chinese_summary(item)),
                    content_analysis=_json_text(data, "content_analysis", _paper_analysis(item, profile)),
                    critique=_json_text(data, "critique", _paper_critique(item)),
                    follow_up=_json_text(data, "follow_up", _paper_follow_up(item)),
                    evidence_scope=_json_text(data, "evidence_scope", reading.evidence_scope),
                    reading_path=reading.reading_path,
                    source_path=reading.source_path,
                    confidence=_json_text(data, "confidence", "medium", 40),
                )
        except Exception as exc:
            LOGGER.warning("LLM paper insight failed for %s; using deterministic fallback: %s", item.paper.uid, exc)
    return PaperInsight(
        paper_uid=item.paper.uid,
        profile_id=profile.id,
        chinese_summary=_paper_chinese_summary(item),
        content_analysis=_paper_analysis(item, profile),
        critique=_paper_critique(item),
        follow_up=_paper_follow_up(item),
        evidence_scope=f"{reading.evidence_scope}; metadata-only fallback analysis",
        reading_path=reading.reading_path,
        source_path=reading.source_path,
        confidence="low",
    )


def _paper_prompt(profile: WatchProfile, item: ClassifiedPaper, reading: PaperReading) -> str:
    paper = item.paper
    authors = ", ".join(paper.authors) if paper.authors else "Unknown"
    excerpt = reading.source_excerpt or "No public full-text/source-page excerpt was available."
    return f"""
Profile:
- id: {profile.id}
- name: {profile.name}
- description: {profile.description}

Paper metadata:
- title: {paper.title}
- authors: {authors}
- journal/source: {paper.journal or paper.source}
- published_at: {paper.published_at}
- doi: {paper.doi or ""}
- url: {paper.url}
- labels: {", ".join(item.labels)}
- score: {item.total_score}/100
- classifier reasons: {"; ".join(item.reasons)}

Abstract:
{paper.abstract or "No abstract was available from source metadata."}

Additional reading evidence:
{excerpt}

Evidence scope:
{reading.evidence_scope}

Write Chinese scientific analysis for a researcher tracking this field. Return strict JSON:
{{
  "chinese_summary": "2-4 sentences. Translate/summarize what the paper actually studies and claims.",
  "content_analysis": "Analyze method, experiment/device/theory/ML idea, results, and relevance. Use concrete terms.",
  "critique": "Point out weak evidence, missing controls, unclear assumptions, limited novelty, or overclaiming.",
  "follow_up": "Concrete checks or next papers/experiments/metrics to look for.",
  "evidence_scope": "State whether you used metadata only, abstract, source page, or PDF excerpt.",
  "confidence": "low|medium|high"
}}
""".strip()


def _json_text(data: dict[str, Any], key: str, fallback: str, limit: int = 2400) -> str:
    value = data.get(key)
    if value is None:
        return fallback
    if isinstance(value, list):
        text = "\n".join(str(item) for item in value)
    else:
        text = str(value)
    cleaned = clean_text(text)
    return cleaned[:limit].strip() or fallback


def _insight_lookup(digest: Digest):
    insights = {insight.paper_uid: insight for insight in digest.paper_insights}

    def lookup(item: ClassifiedPaper) -> PaperInsight:
        return insights.get(
            item.paper.uid,
            PaperInsight(
                paper_uid=item.paper.uid,
                profile_id=digest.profile.id,
                chinese_summary=_paper_chinese_summary(item),
                content_analysis=_paper_analysis(item, digest.profile),
                critique=_paper_critique(item),
                follow_up=_paper_follow_up(item),
                evidence_scope="source metadata only; legacy digest without stored paper insight",
                confidence="low",
            ),
        )

    return lookup


def _paper_chinese_summary(item: ClassifiedPaper) -> str:
    paper = item.paper
    abstract = clean_text(paper.abstract)
    if not abstract:
        return "来源元数据未提供摘要，当前只能基于标题、期刊和关键词判断。"
    return (
        f"这篇文章主要讨论《{paper.title}》。从摘要看，核心内容是："
        f"{first_sentence(abstract, 360)}"
    )


def _paper_analysis(item: ClassifiedPaper, profile: WatchProfile) -> str:
    labels = "、".join(item.labels) or "未分类方向"
    reasons = "；".join(item.reasons[:3])
    source = item.paper.journal or item.paper.source
    return (
        "未启用 LLM 阅读时，下面只是分类器基于标题、来源、关键词和摘要元数据给出的解释，"
        "不是对论文正文的内容分析。"
        f"该文献与 `{profile.name}` 的关系主要体现在 {labels}。"
        f"当前评分为 {item.total_score}/100，其中相关性 {item.relevance_score}、"
        f"新颖性 {item.novelty_score}、证据完整度 {item.evidence_score}。"
        f"入选依据是：{reasons}。"
        f"来源为 {source}，因此更适合作为{'重点精读' if item.total_score >= 90 else '候选跟踪'}材料。"
    )


def _paper_critique(item: ClassifiedPaper) -> str:
    notes: list[str] = []
    notes.append("未启用 LLM 阅读或未取得正文证据时，这不是内容层面的 judge，只是元数据风险提示。")
    if item.evidence_score < 30:
        notes.append("元数据证据偏少，最好打开原文确认方法、数据和结论。")
    if item.relevance_score < 35:
        notes.append("与当前频道的关键词关联不强，可能只是边缘相关。")
    if item.total_score < 80:
        notes.append("综合优先级不高，不建议占用大量精读时间。")
    if not item.paper.doi and "arxiv" not in item.paper.url.lower():
        notes.append("缺少 DOI 或稳定编号，后续引用需要谨慎。")
    if not notes:
        notes.append("主要风险在于摘要层面的判断有限，具体贡献仍需阅读正文、图表和实验/模拟设置。")
    return " ".join(notes)


def _paper_follow_up(item: ClassifiedPaper) -> str:
    label_text = "、".join(item.labels)
    if "machine-learning" in item.labels:
        return "建议重点检查数据集规模、泛化测试、基线方法和不确定性处理，判断是否能迁移到诊断、反演或实验优化。"
    if "diagnostic" in item.labels:
        return "建议跟进仪器分辨率、标定方法、信噪比、动态范围，以及是否能在高能量密度实验中稳定部署。"
    if "theory" in item.labels:
        return "建议检查模型假设、边界条件、数值收敛性，以及是否能和实验观测或已有 benchmark 对上。"
    if "experiment" in item.labels:
        return "建议查看实验平台、shot 条件、诊断链条和误差分析，确认结论是否能推广到其他装置。"
    return f"建议按标签 {label_text or 'research'} 做后续阅读，并优先确认方法细节和证据强度。"
