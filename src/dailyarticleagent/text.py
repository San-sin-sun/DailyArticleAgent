from __future__ import annotations

import hashlib
import html
import re
from datetime import date, datetime

HTML_TAG = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"\s+")
PUNCT = re.compile(r"[^\w\s-]", re.UNICODE)


def clean_text(value: str | None) -> str:
    without_tags = HTML_TAG.sub(" ", value or "")
    unescaped = html.unescape(without_tags)
    return WHITESPACE.sub(" ", unescaped).strip()


def normalize_key(value: str) -> str:
    lowered = clean_text(value).lower()
    return PUNCT.sub("", lowered)


def stable_uid(*parts: str | None) -> str:
    raw = "|".join(clean_text(part) for part in parts if part)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def contains_any(text: str, needles: tuple[str, ...]) -> list[str]:
    haystack = normalize_key(text)
    return [needle for needle in needles if normalize_key(needle) in haystack]


def first_sentence(text: str, limit: int = 260) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    pieces = re.split(r"(?<=[.!?。！？])\s+", cleaned, maxsplit=1)
    sentence = pieces[0]
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1].rstrip() + "..."
