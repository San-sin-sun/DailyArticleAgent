from __future__ import annotations

from .models import ClassifiedPaper, Paper, PaperStatus, WatchProfile
from .text import contains_any, first_sentence


def classify_papers(
    profile: WatchProfile,
    papers: list[Paper],
    feedback_adjustments: dict[str, int] | None = None,
) -> list[ClassifiedPaper]:
    classified = classify_all_papers(profile, papers, feedback_adjustments=feedback_adjustments)
    return select_classified(profile, classified)


def classify_all_papers(
    profile: WatchProfile,
    papers: list[Paper],
    feedback_adjustments: dict[str, int] | None = None,
) -> list[ClassifiedPaper]:
    return [_classify(profile, paper, (feedback_adjustments or {}).get(paper.uid, 0)) for paper in papers]


def select_classified(
    profile: WatchProfile,
    classified: list[ClassifiedPaper],
) -> list[ClassifiedPaper]:
    selected = [paper for paper in classified if paper.status == PaperStatus.SELECTED]
    selected.sort(key=lambda item: item.total_score, reverse=True)
    return selected[: profile.max_items]


def _classify(profile: WatchProfile, paper: Paper, feedback_adjustment: int = 0) -> ClassifiedPaper:
    text = f"{paper.title}\n{paper.abstract}\n{paper.journal or ''}"
    hits = contains_any(text, profile.keywords)
    excludes = contains_any(text, profile.exclude_keywords)

    relevance = min(70, len(hits) * 18)
    if profile.broad_discovery and hits:
        relevance = max(relevance, 45)
    preferred_source_tokens = ("nature", "science", "acm", "ieee", "arxiv", "transactions", "conference")
    source_text = f"{paper.source} {paper.journal or ''}".lower()
    if any(source in source_text for source in preferred_source_tokens):
        relevance += 8
    relevance = max(0, relevance - len(excludes) * 25)

    novelty = 20
    title_lower = paper.title.lower()
    if any(word in title_lower for word in ("new", "novel", "first", "demonstration", "measurement")):
        novelty += 12
    if any(word in title_lower for word in ("review", "survey", "overview")):
        novelty -= 5

    evidence = 10
    if paper.abstract:
        evidence += 15
    if paper.doi or "arxiv" in paper.url.lower():
        evidence += 10
    if paper.published_at:
        evidence += 5

    total = max(0, min(100, relevance + novelty + evidence + feedback_adjustment))
    is_selected = (hits or profile.broad_discovery) and not (excludes and total < 50)
    status = PaperStatus.SELECTED if is_selected else PaperStatus.REJECTED
    reasons = tuple(_reasons(paper, hits, excludes, feedback_adjustment))
    labels = tuple(_labels(paper, hits))
    return ClassifiedPaper(
        paper=paper,
        profile_id=profile.id,
        relevance_score=max(0, min(100, relevance)),
        novelty_score=max(0, min(100, novelty)),
        evidence_score=max(0, min(100, evidence)),
        total_score=total,
        reasons=reasons,
        labels=labels,
        status=status,
    )


def _reasons(paper: Paper, hits: list[str], excludes: list[str], feedback_adjustment: int = 0) -> list[str]:
    reasons: list[str] = []
    if hits:
        reasons.append("关键词命中: " + ", ".join(hits[:5]))
    if paper.journal:
        reasons.append(f"来源: {paper.journal}")
    if paper.abstract:
        reasons.append("摘要证据: " + first_sentence(paper.abstract))
    if excludes:
        reasons.append("排除词命中: " + ", ".join(excludes[:3]))
    if feedback_adjustment:
        reasons.append(f"人工反馈调分: {feedback_adjustment:+d}")
    return reasons or ["未找到足够证据"]


def _labels(paper: Paper, hits: list[str]) -> list[str]:
    text = f"{paper.title} {paper.abstract}".lower()
    labels: list[str] = []
    buckets = {
        "experiment": ("experiment", "measurement", "demonstration", "shot", "implosion"),
        "facility": ("facility", "platform", "beamline", "target chamber", "driver"),
        "diagnostic": ("diagnostic", "detector", "spectrometer", "radiography", "camera"),
        "theory": ("theory", "model", "simulation", "hydrodynamic", "kinetic"),
        "machine-learning": ("machine learning", "deep learning", "neural", "bayesian", "surrogate"),
    }
    for label, words in buckets.items():
        if any(word in text for word in words):
            labels.append(label)
    for hit in hits[:3]:
        slug = hit.lower().replace(" ", "-")
        if slug not in labels:
            labels.append(slug)
    return labels or ["research"]
