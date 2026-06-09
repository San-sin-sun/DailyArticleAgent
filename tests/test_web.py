from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from dailyarticleagent import reader as reader_module
from dailyarticleagent.classifier import classify_all_papers
from dailyarticleagent.models import Digest, DigestPeriod, Paper, PaperInsight, RunAction, SourceConfig, WatchProfile
from dailyarticleagent.storage import Repository
from dailyarticleagent.web import create_app


def test_create_web_app() -> None:
    app = create_app()

    assert app.title == "DailyArticleAgent API"


def test_papers_api_returns_insight(tmp_path) -> None:
    db_path = tmp_path / "articles.sqlite"
    repo = Repository(db_path)
    profile = WatchProfile(
        id="ai_systems_example",
        name="AI Systems Example",
        description="",
        language="zh-CN",
        max_items=10,
        keywords=("retrieval agent",),
        exclude_keywords=(),
        sources=(SourceConfig(name="arxiv", kind="arxiv"),),
    )
    paper = Paper(
        uid="p1",
        title="Retrieval agent evaluation study",
        authors=(),
        abstract="A retrieval agent evaluation study.",
        source="arxiv",
        source_kind="arxiv",
        published_at=date(2026, 6, 9),
        discovered_at=datetime.now(UTC),
        url="https://example.test",
    )
    repo.save_papers([paper])
    repo.save_classifications(classify_all_papers(profile, [paper]))
    repo.save_digest(
        Digest(
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
                    critique="judge",
                    follow_up="follow",
                    evidence_scope="metadata",
                    confidence="medium",
                ),
            ),
        )
    )
    repo.close()

    client = TestClient(create_app(db_path=db_path))
    response = client.get("/api/papers")

    assert response.status_code == 200
    assert response.json()[0]["insight"]["content_analysis"] == "内容 insight"


def test_feedback_api_updates_latest_paper_feedback(tmp_path) -> None:
    db_path = tmp_path / "articles.sqlite"
    repo = Repository(db_path)
    profile = _profile()
    paper = _paper()
    repo.save_papers([paper])
    repo.save_classifications(classify_all_papers(profile, [paper]))
    repo.close()

    client = TestClient(create_app(config_path=Path("config/watch_profiles.yaml"), db_path=db_path))
    response = client.post(
        "/api/feedback",
        json={"paper_uid": paper.uid, "profile_id": profile.id, "rating": "save", "note": "important"},
    )
    papers = client.get(f"/api/papers?profile_id={profile.id}").json()

    assert response.status_code == 200
    assert papers[0]["feedback_rating"] == "save"


def test_runs_api_lists_run_history(tmp_path) -> None:
    db_path = tmp_path / "articles.sqlite"
    repo = Repository(db_path)
    run_id = repo.start_run(RunAction.REWRITE_DIGESTS, "all")
    repo.close()

    client = TestClient(create_app(config_path=Path("config/watch_profiles.yaml"), db_path=db_path))
    response = client.get("/api/runs")

    assert response.status_code == 200
    assert response.json()[0]["id"] == run_id


def test_profile_config_api_validates_yaml(tmp_path) -> None:
    config_path = tmp_path / "profiles.yaml"
    config_path.write_text(
        """
profiles:
  - id: test
    name: Test
    language: zh-CN
    max_items: 1
    keywords: [laser]
    exclude_keywords: []
    sources:
      - name: arxiv
        kind: arxiv
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path=config_path, db_path=tmp_path / "articles.sqlite"))

    bad = client.put("/api/profile-config", json={"yaml_text": "profiles: []"})
    good = client.put("/api/profile-config", json={"yaml_text": config_path.read_text(encoding="utf-8")})

    assert bad.status_code == 400
    assert good.status_code == 200
    assert config_path.with_suffix(".yaml.bak").exists()


def test_upload_pdf_reanalyzes_paper_from_user_file(tmp_path, monkeypatch) -> None:
    def fake_pdf_to_text(content: bytes, limit: int) -> str:
        return (
            "Uploaded PDF evidence about retrieval agent benchmarks and timing measurements. "
            "The paper describes benchmark calibration, timing response, uncertainty sources, "
            "signal processing, evaluation protocol, and implications for software "
            "agent experiments. "
        ) * 3

    monkeypatch.setattr(reader_module, "_pdf_to_text", fake_pdf_to_text)
    db_path = tmp_path / "articles.sqlite"
    content_dir = tmp_path / "content"
    repo = Repository(db_path)
    profile = _profile()
    paper = _paper()
    repo.save_papers([paper])
    repo.save_classifications(classify_all_papers(profile, [paper]))
    repo.close()

    client = TestClient(
        create_app(
            config_path=Path("config/watch_profiles.yaml"),
            db_path=db_path,
            content_dir=content_dir,
        )
    )
    response = client.post(
        f"/api/papers/{paper.uid}/upload-pdf?profile_id={profile.id}&use_llm=false",
        files={"file": ("paper.pdf", b"%PDF fake", "application/pdf")},
    )
    papers = client.get(f"/api/papers?profile_id={profile.id}").json()

    assert response.status_code == 200
    assert "local PDF" in papers[0]["insight"]["evidence_scope"]
    assert papers[0]["insight"]["source_path"]


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


def _paper() -> Paper:
    return Paper(
        uid="p1",
        title="Retrieval agent evaluation study",
        authors=(),
        abstract="A retrieval agent evaluation study.",
        source="arxiv",
        source_kind="arxiv",
        published_at=date(2026, 6, 9),
        discovered_at=datetime.now(UTC),
        url="https://example.test",
    )
