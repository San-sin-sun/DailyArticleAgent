from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

import feedparser
import httpx

from .models import Paper, SourceConfig
from .text import clean_text, parse_date, stable_uid

LOGGER = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class PaperSource(Protocol):
    def fetch(self, source: SourceConfig, since: date, until: date) -> list[Paper]:
        ...


class ArxivSource:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch(self, source: SourceConfig, since: date, until: date) -> list[Paper]:
        params = {
            "search_query": source.query or "all:*",
            "start": 0,
            "max_results": source.limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        response = self.client.get(f"{ARXIV_API}?{urlencode(params)}")
        response.raise_for_status()
        root = ET.fromstring(response.text)
        papers: list[Paper] = []
        for entry in root.findall("atom:entry", ARXIV_NS):
            published = parse_date(_node_text(entry, "atom:published"))
            if published and not _in_window(published, since, until):
                continue
            title = clean_text(_node_text(entry, "atom:title"))
            abstract = clean_text(_node_text(entry, "atom:summary"))
            raw_id = clean_text(_node_text(entry, "atom:id"))
            authors = tuple(
                clean_text(_node_text(author, "atom:name"))
                for author in entry.findall("atom:author", ARXIV_NS)
            )
            doi = clean_text(_node_text(entry, "arxiv:doi")) or None
            url = raw_id or _entry_link(entry)
            uid = stable_uid(doi, raw_id, title)
            papers.append(
                Paper(
                    uid=uid,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    source=source.name,
                    source_kind=source.kind,
                    published_at=published,
                    discovered_at=datetime.now(UTC),
                    url=url,
                    doi=doi,
                    journal="arXiv",
                    raw_id=raw_id,
                )
            )
        return papers


class RssSource:
    def fetch(self, source: SourceConfig, since: date, until: date) -> list[Paper]:
        if not source.url:
            return []
        feed = feedparser.parse(source.url)
        papers: list[Paper] = []
        for entry in feed.entries[: source.limit]:
            published = _feed_date(entry)
            if published and not _in_window(published, since, until):
                continue
            title = clean_text(getattr(entry, "title", ""))
            abstract = clean_text(
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or getattr(entry, "subtitle", "")
            )
            link = clean_text(getattr(entry, "link", ""))
            doi = _doi_from_entry(entry)
            authors = _feed_authors(entry)
            uid = stable_uid(doi, link, title)
            papers.append(
                Paper(
                    uid=uid,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    source=source.name,
                    source_kind=source.kind,
                    published_at=published,
                    discovered_at=datetime.now(UTC),
                    url=link,
                    doi=doi,
                    journal=clean_text(getattr(feed.feed, "title", "")) or source.name,
                    raw_id=clean_text(getattr(entry, "id", "")) or link,
                )
            )
        return papers


class CrossrefSource:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch(self, source: SourceConfig, since: date, until: date) -> list[Paper]:
        time.sleep(0.25)
        filters = [f"from-pub-date:{since.isoformat()}", f"until-pub-date:{until.isoformat()}"]
        if source.issn:
            filters.append(f"issn:{source.issn}")
        params = {
            "filter": ",".join(filters),
            "rows": source.limit,
            "sort": "published",
            "order": "desc",
            "select": (
                "DOI,title,author,published-print,published-online,"
                "container-title,abstract,URL,issued"
            ),
        }
        if source.query:
            params["query.bibliographic"] = source.query
        response = self.client.get(CROSSREF_API, params=params)
        if response.status_code == 429:
            time.sleep(2.0)
            response = self.client.get(CROSSREF_API, params=params)
        response.raise_for_status()
        items = response.json().get("message", {}).get("items", [])
        papers: list[Paper] = []
        for item in items:
            title = clean_text((item.get("title") or [""])[0])
            if not title:
                continue
            published = _crossref_date(item)
            if published and not _in_window(published, since, until):
                continue
            doi = clean_text(item.get("DOI")) or None
            url = clean_text(item.get("URL")) or (f"https://doi.org/{doi}" if doi else "")
            journal = clean_text((item.get("container-title") or [""])[0]) or source.name
            authors = tuple(_crossref_author(author) for author in item.get("author", []))
            abstract = _strip_crossref_abstract(clean_text(item.get("abstract")))
            uid = stable_uid(doi, url, title)
            papers.append(
                Paper(
                    uid=uid,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    source=source.name,
                    source_kind=source.kind,
                    published_at=published,
                    discovered_at=datetime.now(UTC),
                    url=url,
                    doi=doi,
                    journal=journal,
                    raw_id=doi,
                )
            )
        return papers


class SourceRegistry:
    def __init__(self) -> None:
        self.sources: dict[str, PaperSource] = {
            "arxiv": ArxivSource(),
            "rss": RssSource(),
            "crossref": CrossrefSource(),
        }

    def fetch(self, sources: Iterable[SourceConfig], since: date, until: date) -> list[Paper]:
        papers: list[Paper] = []
        for source in sources:
            adapter = self.sources.get(source.kind)
            if not adapter:
                LOGGER.warning("Skipping unknown source kind %s for %s", source.kind, source.name)
                continue
            try:
                papers.extend(adapter.fetch(source, since, until))
            except Exception as exc:
                LOGGER.warning("Source %s failed: %s", source.name, exc)
        return dedupe_papers(papers)


def dedupe_papers(papers: Iterable[Paper]) -> list[Paper]:
    seen: set[str] = set()
    result: list[Paper] = []
    for paper in papers:
        key = paper.doi.lower() if paper.doi else paper.uid
        if key in seen:
            continue
        seen.add(key)
        result.append(paper)
    return result


def default_since(days: int) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    return today - timedelta(days=days), today


def _in_window(value: date, since: date, until: date) -> bool:
    return since <= value <= until


def _node_text(node: ET.Element, path: str) -> str:
    child = node.find(path, ARXIV_NS)
    return child.text if child is not None and child.text else ""


def _entry_link(entry: ET.Element) -> str:
    link = entry.find("atom:link", ARXIV_NS)
    return link.attrib.get("href", "") if link is not None else ""


def _feed_date(entry: object) -> date | None:
    for attr in ("published", "updated", "created"):
        parsed = parse_date(clean_text(getattr(entry, attr, "")))
        if parsed:
            return parsed
    parsed_tuple = getattr(entry, "published_parsed", None) or getattr(
        entry,
        "updated_parsed",
        None,
    )
    if parsed_tuple:
        return date(parsed_tuple.tm_year, parsed_tuple.tm_mon, parsed_tuple.tm_mday)
    return None


def _feed_authors(entry: object) -> tuple[str, ...]:
    authors = getattr(entry, "authors", None)
    if authors:
        return tuple(clean_text(author.get("name", "")) for author in authors if author.get("name"))
    author = clean_text(getattr(entry, "author", ""))
    return (author,) if author else ()


def _doi_from_entry(entry: object) -> str | None:
    for attr in ("dc_identifier", "prism_doi", "doi"):
        value = clean_text(getattr(entry, attr, ""))
        if value:
            return value.replace("doi:", "").strip()
    link = clean_text(getattr(entry, "link", ""))
    if "doi.org/" in link:
        return link.split("doi.org/", 1)[1].strip()
    return None


def _crossref_date(item: dict) -> date | None:
    for key in ("published-online", "published-print", "issued"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            year, month, day = (parts[0] + [1, 1])[:3]
            return date(int(year), int(month), int(day))
    return None


def _crossref_author(author: dict) -> str:
    given = clean_text(author.get("given"))
    family = clean_text(author.get("family"))
    return clean_text(f"{given} {family}") or clean_text(author.get("name"))


def _strip_crossref_abstract(value: str) -> str:
    return (
        value.replace("<jats:p>", "")
        .replace("</jats:p>", "")
        .replace("<p>", "")
        .replace("</p>", "")
    )
