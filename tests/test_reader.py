from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from dailyarticleagent import reader as reader_module
from dailyarticleagent.models import Paper
from dailyarticleagent.reader import PaperReader


def test_reader_saves_public_html_evidence(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body><h1>Benchmark paper</h1><p>Calibrated retrieval benchmark evidence.</p></body></html>",
        )

    paper = Paper(
        uid="p1",
        title="Retrieval agent benchmark",
        authors=(),
        abstract="",
        source="rss",
        source_kind="rss",
        published_at=date(2026, 6, 9),
        discovered_at=datetime.now(UTC),
        url="https://example.test/paper",
    )
    reader = PaperReader(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        readings_dir=tmp_path,
        min_excerpt_chars=10,
    )

    reading = reader.read(paper)

    assert "Calibrated retrieval benchmark evidence" in reading.source_excerpt
    assert reading.reading_path is not None
    assert reading.source_path is not None
    assert "Calibrated retrieval benchmark evidence" in Path(reading.reading_path).read_text()


def test_reader_rejects_too_short_html_evidence(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>OK</html>")

    paper = Paper(
        uid="p1",
        title="Retrieval agent benchmark",
        authors=(),
        abstract="",
        source="rss",
        source_kind="rss",
        published_at=date(2026, 6, 9),
        discovered_at=datetime.now(UTC),
        url="https://example.test/paper",
    )
    reader = PaperReader(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        readings_dir=tmp_path,
    )

    reading = reader.read(paper)

    assert reading.source_excerpt == ""
    assert reading.reading_path is None
    assert reading.source_path is None
    assert "no substantial readable text" in reading.evidence_scope


def test_reader_follows_public_pdf_link_discovered_in_html(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF fake")
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<html><body><a href="/article.pdf">PDF</a></body></html>',
        )

    def fake_pdf_to_text(content: bytes, limit: int) -> str:
        return "Detailed public PDF evidence about retrieval benchmark calibration and evaluation timing."

    monkeypatch.setattr(reader_module, "_pdf_to_text", fake_pdf_to_text)
    paper = Paper(
        uid="p1",
        title="Retrieval agent benchmark",
        authors=(),
        abstract="",
        source="rss",
        source_kind="rss",
        published_at=date(2026, 6, 9),
        discovered_at=datetime.now(UTC),
        url="https://example.test/paper",
    )
    reader = PaperReader(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        readings_dir=tmp_path,
        min_excerpt_chars=10,
    )

    reading = reader.read(paper)

    assert "evaluation timing" in reading.source_excerpt
    assert "discovered public PDF" in reading.evidence_scope
    assert reading.source_path is not None


def test_reader_uses_local_pdf_before_network(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    local_pdf_dir = tmp_path / "local-pdfs"
    local_pdf_dir.mkdir()
    (local_pdf_dir / "p-local.pdf").write_bytes(b"%PDF fake")

    def fake_pdf_to_text(content: bytes, limit: int) -> str:
        return "Local PDF evidence about retrieval agent benchmarks with enough text."

    monkeypatch.setattr(reader_module, "_pdf_to_text", fake_pdf_to_text)
    paper = Paper(
        uid="p-local",
        title="Retrieval agent benchmark",
        authors=(),
        abstract="",
        source="rss",
        source_kind="rss",
        published_at=date(2026, 6, 9),
        discovered_at=datetime.now(UTC),
        url="https://example.test/paper",
    )
    reader = PaperReader(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
        readings_dir=tmp_path / "readings",
        local_pdf_dir=local_pdf_dir,
        min_excerpt_chars=10,
    )

    reading = reader.read(paper)

    assert "Local PDF evidence" in reading.source_excerpt
    assert "local PDF" in reading.evidence_scope
