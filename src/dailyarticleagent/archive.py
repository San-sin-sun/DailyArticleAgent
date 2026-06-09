from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .service import AppPaths


@dataclass(frozen=True)
class ArchiveManifest:
    created_at: str
    config_path: str
    db_path: str
    content_dir: str


def export_data(paths: AppPaths, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = ArchiveManifest(
        created_at=datetime.now(UTC).isoformat(),
        config_path=str(paths.config_path),
        db_path=str(paths.db_path),
        content_dir=str(paths.content_dir),
    )
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(manifest.__dict__, ensure_ascii=False, indent=2))
        _write_file(archive, paths.config_path, "config/watch_profiles.yaml")
        _write_file(archive, paths.db_path, "data/articles.sqlite")
        _write_dir(archive, paths.content_dir, "content")
    return output_path


def restore_data(paths: AppPaths, archive_path: Path, replace: bool = False) -> None:
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    targets = [paths.config_path, paths.db_path, paths.content_dir]
    if not replace:
        existing = [str(path) for path in targets if path.exists()]
        if existing:
            raise FileExistsError("Refusing to overwrite existing paths without --replace: " + ", ".join(existing))

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp)
        _restore_file(temp / "config" / "watch_profiles.yaml", paths.config_path)
        _restore_file(temp / "data" / "articles.sqlite", paths.db_path)
        _restore_dir(temp / "content", paths.content_dir)


def _write_file(archive: zipfile.ZipFile, source: Path, target: str) -> None:
    if source.exists() and source.is_file():
        archive.write(source, target)


def _write_dir(archive: zipfile.ZipFile, source: Path, target_root: str) -> None:
    if not source.exists():
        return
    for path in source.rglob("*"):
        if path.is_file():
            archive.write(path, str(Path(target_root) / path.relative_to(source)).replace("\\", "/"))


def _restore_file(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _restore_dir(source: Path, target: Path) -> None:
    if not source.exists():
        return
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
