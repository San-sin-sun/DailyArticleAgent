from __future__ import annotations

import os
from pathlib import Path

import yaml

from .models import SourceConfig, WatchProfile

DEFAULT_CONFIG_PATH = Path("config/watch_profiles.yaml")
LOCAL_CONFIG_PATH = Path("config/watch_profiles.local.yaml")
DEFAULT_DB_PATH = Path("data/articles.sqlite")
DEFAULT_CONTENT_DIR = Path("content")


def resolve_config_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    env_path = os.getenv("DAA_CONFIG_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    if LOCAL_CONFIG_PATH.exists():
        return LOCAL_CONFIG_PATH
    return DEFAULT_CONFIG_PATH


def resolve_runtime_path(path: Path | None, env_name: str, default: Path) -> Path:
    if path is not None:
        return path
    env_path = os.getenv(env_name, "").strip()
    return Path(env_path).expanduser() if env_path else default


def load_profiles(path: Path | None = None) -> dict[str, WatchProfile]:
    config_path = resolve_config_path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Profile config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    profiles: dict[str, WatchProfile] = {}
    for item in data.get("profiles", []):
        sources = tuple(SourceConfig(**source) for source in item.get("sources", []))
        profile = WatchProfile(
            id=item["id"],
            name=item["name"],
            description=item.get("description", ""),
            language=item.get("language", "zh-CN"),
            max_items=int(item.get("max_items", 12)),
            keywords=tuple(item.get("keywords", [])),
            exclude_keywords=tuple(item.get("exclude_keywords", [])),
            sources=sources,
            broad_discovery=bool(item.get("broad_discovery", False)),
        )
        profiles[profile.id] = profile

    if not profiles:
        raise ValueError(f"No profiles configured in {config_path}")
    return profiles
