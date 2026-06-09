from __future__ import annotations

from typer.testing import CliRunner

from dailyarticleagent.cli import app


def test_schedule_help_prints_daily_and_weekly_commands() -> None:
    result = CliRunner().invoke(app, ["schedule-help", "all", "--use-llm"])

    assert result.exit_code == 0
    assert "DailyArticleAgent Daily" in result.output
    assert "DailyArticleAgent Weekly" in result.output
    assert "daily all --use-llm" in result.output
    assert "weekly all --use-llm" in result.output


def test_reanalyze_requires_llm(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "reanalyze",
            "ai_systems_example",
            "--config",
            "config/watch_profiles.yaml",
            "--db",
            str(tmp_path / "articles.sqlite"),
            "--content",
            str(tmp_path / "content"),
        ],
    )

    assert result.exit_code != 0
    assert "requires --use-llm" in result.output


def test_rewrite_digests_command_handles_empty_database(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "rewrite-digests",
            "all",
            "--config",
            "config/watch_profiles.yaml",
            "--db",
            str(tmp_path / "articles.sqlite"),
            "--content",
            str(tmp_path / "content"),
        ],
    )

    assert result.exit_code == 0
    assert "rewrote 0 digest files" in result.output
