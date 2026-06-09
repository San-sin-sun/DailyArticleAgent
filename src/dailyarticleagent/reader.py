from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import httpx
from pypdf import PdfReader

from .models import Paper
from .text import clean_text, stable_uid

LOGGER = logging.getLogger(__name__)

SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class PaperReading:
    source_excerpt: str
    evidence_scope: str
    reading_path: str | None = None
    source_path: str | None = None


class PaperReader:
    def __init__(
        self,
        client: httpx.Client | None = None,
        fetch_pages: bool = True,
        excerpt_limit: int = 6000,
        readings_dir: Path | None = None,
        min_excerpt_chars: int = 300,
        local_pdf_dir: Path | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "DailyArticleAgent/0.1"},
        )
        self.fetch_pages = fetch_pages
        self.excerpt_limit = excerpt_limit
        self.readings_dir = readings_dir
        self.min_excerpt_chars = min_excerpt_chars
        self.local_pdf_dir = local_pdf_dir

    def read(self, paper: Paper) -> PaperReading:
        if not self.fetch_pages:
            return PaperReading("", "source metadata only; public page fetching is disabled")
        local_excerpt, local_source = self._read_local_pdf(paper)
        if self._usable_excerpt(local_excerpt):
            reading_path = self._save_reading(paper, local_excerpt)
            return PaperReading(
                local_excerpt,
                f"source metadata plus local PDF text excerpt ({len(local_excerpt)} characters)",
                reading_path=reading_path,
                source_path=local_source,
            )
        if not paper.url:
            return PaperReading("", "source metadata only; no source URL was available")
        if _looks_like_arxiv(paper):
            pdf = _arxiv_pdf_url(paper.url)
            pdf_excerpt, source_path = self._read_pdf_url(paper, pdf)
            if self._usable_excerpt(pdf_excerpt):
                reading_path = self._save_reading(paper, pdf_excerpt)
                return PaperReading(
                    pdf_excerpt,
                    f"source metadata plus arXiv PDF text excerpt ({len(pdf_excerpt)} characters)",
                    reading_path=reading_path,
                    source_path=source_path,
                )
        if paper.doi and "doi.org" not in paper.url.lower():
            doi_url = f"https://doi.org/{paper.doi}"
            doi_reading = self._read_public_url(paper, doi_url, "DOI resolver landing page")
            if self._usable_excerpt(doi_reading.source_excerpt):
                return doi_reading
            pdf_reading = self._read_discovered_pdf(paper, doi_url, doi_reading.source_excerpt)
            if self._usable_excerpt(pdf_reading.source_excerpt):
                return pdf_reading
        return self._read_public_url(paper, paper.url, "public source page")

    def _read_public_url(self, paper: Paper, url: str, label: str) -> PaperReading:
        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.info("Could not fetch %s for %s: %s", label, paper.uid, exc)
            return PaperReading("", f"source metadata only; {label} fetch failed")

        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type:
            source_path = self._save_source(paper, response.content, ".pdf")
            excerpt = _pdf_to_text(response.content, self.excerpt_limit)
            if excerpt:
                reading_path = self._save_reading(paper, excerpt)
                return PaperReading(
                    excerpt,
                    f"source metadata plus {label} PDF text excerpt ({len(excerpt)} characters)",
                    reading_path=reading_path,
                    source_path=source_path,
                )
            return PaperReading("", f"source metadata only; {label} URL points to unreadable or too-short PDF text")
        if "html" not in content_type and "text" not in content_type and response.text.startswith("%PDF"):
            source_path = self._save_source(paper, response.content, ".pdf")
            excerpt = _pdf_to_text(response.content, self.excerpt_limit)
            if self._usable_excerpt(excerpt):
                reading_path = self._save_reading(paper, excerpt)
                return PaperReading(
                    excerpt,
                    f"source metadata plus {label} PDF text excerpt ({len(excerpt)} characters)",
                    reading_path=reading_path,
                    source_path=source_path,
                )
            return PaperReading("", f"source metadata only; {label} returned unreadable or too-short PDF text")

        excerpt = _html_to_text(response.text, self.excerpt_limit)
        pdf_reading = self._read_discovered_pdf(paper, url, response.text)
        if self._usable_excerpt(pdf_reading.source_excerpt):
            return pdf_reading
        if not self._usable_excerpt(excerpt):
            return PaperReading("", f"source metadata only; {label} had no substantial readable text")
        source_path = self._save_source(paper, response.content, ".html")
        reading_path = self._save_reading(paper, excerpt)
        return PaperReading(
            excerpt,
            f"source metadata plus {label} excerpt ({len(excerpt)} characters)",
            reading_path=reading_path,
            source_path=source_path,
        )

    def _read_discovered_pdf(self, paper: Paper, base_url: str, html: str) -> PaperReading:
        for url in _pdf_links(base_url, html)[:3]:
            excerpt, source_path = self._read_pdf_url(paper, url)
            if self._usable_excerpt(excerpt):
                reading_path = self._save_reading(paper, excerpt)
                return PaperReading(
                    excerpt,
                    f"source metadata plus discovered public PDF text excerpt ({len(excerpt)} characters)",
                    reading_path=reading_path,
                    source_path=source_path,
                )
        return PaperReading("", "source metadata only; no usable discovered PDF link")

    def _read_local_pdf(self, paper: Paper) -> tuple[str, str | None]:
        if not self.local_pdf_dir or not self.local_pdf_dir.exists():
            return "", None
        candidates = []
        for value in (paper.doi, paper.raw_id, paper.uid):
            if value:
                stem = safe_pdf_stem(value)
                candidates.extend(self.local_pdf_dir.glob(f"*{stem}*.pdf"))
        for path in candidates:
            content = path.read_bytes()
            excerpt = _pdf_to_text(content, self.excerpt_limit)
            if self._usable_excerpt(excerpt):
                source_path = self._save_source(paper, content, ".pdf") or str(path)
                return excerpt, source_path
        return "", None

    def _read_pdf_url(self, paper: Paper, url: str) -> tuple[str, str | None]:
        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.info("Could not fetch PDF page %s: %s", url, exc)
            return "", None
        source_path = self._save_source(paper, response.content, ".pdf")
        return _pdf_to_text(response.content, self.excerpt_limit), source_path

    def _usable_excerpt(self, text: str) -> bool:
        return len(clean_text(text)) >= self.min_excerpt_chars

    def _save_source(self, paper: Paper, content: bytes, suffix: str) -> str | None:
        if not self.readings_dir:
            return None
        path = self.readings_dir / f"{_paper_file_stem(paper)}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def _save_reading(self, paper: Paper, text: str) -> str | None:
        if not self.readings_dir or not text:
            return None
        path = self.readings_dir / f"{_paper_file_stem(paper)}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)


def _html_to_text(value: str, limit: int) -> str:
    without_scripts = SCRIPT_OR_STYLE.sub(" ", value)
    return clean_text(without_scripts)[:limit].strip()


def _pdf_to_text(content: bytes, limit: int) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        chunks = []
        for page in reader.pages[:4]:
            chunks.append(page.extract_text() or "")
            if sum(len(chunk) for chunk in chunks) >= limit:
                break
    except Exception as exc:
        LOGGER.info("Could not extract PDF text: %s", exc)
        return ""
    return clean_text(" ".join(chunks))[:limit].strip()


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "link"}:
            return
        attrs_dict = {name.lower(): value for name, value in attrs if value}
        href = attrs_dict.get("href")
        if href:
            self.links.append(href)


def _pdf_links(base_url: str, html: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    links = []
    for href in parser.links:
        absolute = urljoin(base_url, href)
        if ".pdf" in absolute.lower() or "/pdf" in absolute.lower():
            links.append(absolute)
    return links


def _looks_like_arxiv(paper: Paper) -> bool:
    text = f"{paper.url} {paper.raw_id or ''} {paper.journal or ''}".lower()
    return "arxiv.org" in text


def _arxiv_pdf_url(value: str) -> str:
    cleaned = value.strip()
    if "/pdf/" in cleaned:
        return cleaned
    if "/abs/" in cleaned:
        return cleaned.replace("/abs/", "/pdf/")
    return cleaned.replace("http://arxiv.org/", "https://arxiv.org/")


def _paper_file_stem(paper: Paper) -> str:
    return stable_uid(paper.uid, paper.doi, paper.raw_id, paper.title)


def safe_pdf_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
