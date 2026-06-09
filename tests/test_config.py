from __future__ import annotations

from pathlib import Path

import dailyarticleagent.config as config_module
from dailyarticleagent.config import resolve_config_path, resolve_runtime_path
from dailyarticleagent.service import AppPaths


def test_resolve_config_path_uses_explicit_path(monkeypatch) -> None:
    monkeypatch.setenv("DAA_CONFIG_PATH", "config/from-env.yaml")

    assert resolve_config_path(Path("config/explicit.yaml")) == Path("config/explicit.yaml")


def test_resolve_config_path_uses_env_path(monkeypatch) -> None:
    monkeypatch.setenv("DAA_CONFIG_PATH", "config/from-env.yaml")

    assert resolve_config_path() == Path("config/from-env.yaml")


def test_resolve_config_path_prefers_local_config(monkeypatch, tmp_path) -> None:
    local = tmp_path / "watch_profiles.local.yaml"
    local.write_text("profiles: []", encoding="utf-8")
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local)
    monkeypatch.delenv("DAA_CONFIG_PATH", raising=False)

    assert resolve_config_path() == local


def test_resolve_runtime_path_uses_env_path(monkeypatch) -> None:
    monkeypatch.setenv("DAA_DB_PATH", "data/internal.sqlite")

    assert resolve_runtime_path(None, "DAA_DB_PATH", Path("data/articles.sqlite")) == Path("data/internal.sqlite")


def test_app_paths_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DAA_CONFIG_PATH", "config/watch_profiles.local.yaml")
    monkeypatch.setenv("DAA_DB_PATH", "data/internal.sqlite")
    monkeypatch.setenv("DAA_CONTENT_DIR", "content-internal")

    paths = AppPaths.from_env()

    assert paths.config_path == Path("config/watch_profiles.local.yaml")
    assert paths.db_path == Path("data/internal.sqlite")
    assert paths.content_dir == Path("content-internal")
