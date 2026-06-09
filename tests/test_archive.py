from __future__ import annotations

import zipfile

import pytest

from dailyarticleagent.archive import export_data, restore_data
from dailyarticleagent.service import AppPaths


def test_export_and_restore_data_archive(tmp_path) -> None:
    source = tmp_path / "source"
    paths = AppPaths(
        config_path=source / "config" / "watch_profiles.local.yaml",
        db_path=source / "data" / "articles.sqlite",
        content_dir=source / "content",
    )
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text("profiles: []\n", encoding="utf-8")
    paths.db_path.parent.mkdir(parents=True)
    paths.db_path.write_bytes(b"sqlite")
    (paths.content_dir / "daily").mkdir(parents=True)
    (paths.content_dir / "daily" / "digest.md").write_text("# Digest\n", encoding="utf-8")

    archive_path = export_data(paths, tmp_path / "backup.zip")

    with zipfile.ZipFile(archive_path) as archive:
        assert "metadata.json" in archive.namelist()
        assert "config/watch_profiles.yaml" in archive.namelist()
        assert "data/articles.sqlite" in archive.namelist()
        assert "content/daily/digest.md" in archive.namelist()

    restored = AppPaths(
        config_path=tmp_path / "restore" / "config.yaml",
        db_path=tmp_path / "restore" / "articles.sqlite",
        content_dir=tmp_path / "restore" / "content",
    )
    restore_data(restored, archive_path)

    assert restored.config_path.read_text(encoding="utf-8") == "profiles: []\n"
    assert restored.db_path.read_bytes() == b"sqlite"
    assert (restored.content_dir / "daily" / "digest.md").read_text(encoding="utf-8") == "# Digest\n"


def test_restore_refuses_to_overwrite_without_replace(tmp_path) -> None:
    source = AppPaths(
        config_path=tmp_path / "source" / "config.yaml",
        db_path=tmp_path / "source" / "articles.sqlite",
        content_dir=tmp_path / "source" / "content",
    )
    source.config_path.parent.mkdir(parents=True)
    source.config_path.write_text("profiles: []\n", encoding="utf-8")
    source.db_path.parent.mkdir(parents=True, exist_ok=True)
    source.db_path.write_bytes(b"sqlite")
    source.content_dir.mkdir(parents=True)
    archive_path = export_data(source, tmp_path / "backup.zip")

    target = AppPaths(
        config_path=tmp_path / "target" / "config.yaml",
        db_path=tmp_path / "target" / "articles.sqlite",
        content_dir=tmp_path / "target" / "content",
    )
    target.config_path.parent.mkdir(parents=True)
    target.config_path.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        restore_data(target, archive_path)
