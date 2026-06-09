from __future__ import annotations

from pathlib import Path

import pytest

from dailyarticleagent.models import RunAction, RunStatus
from dailyarticleagent.service import AgentService, AppPaths
from dailyarticleagent.worker import AgentWorker, WorkerSettings


def test_run_with_history_records_failure_and_retry(tmp_path) -> None:
    service = AgentService(
        AppPaths(
            config_path=Path("config/watch_profiles.yaml"),
            db_path=tmp_path / "articles.sqlite",
            content_dir=tmp_path / "content",
        )
    )
    try:
        with pytest.raises(KeyError):
            service.run_with_history(RunAction.DAILY, "missing-profile")

        failed = service.repo.list_runs(status=RunStatus.FAILED)
        assert len(failed) == 1
        assert failed[0]["profile_id"] == "missing-profile"
        assert "Unknown profile" in failed[0]["error"]

        with pytest.raises(KeyError):
            service.retry_run(failed[0]["id"])

        retries = service.repo.list_runs(status=RunStatus.FAILED)
        assert len(retries) == 2
        assert retries[0]["parent_run_id"] == failed[0]["id"]
        assert retries[0]["attempts"] == 2
    finally:
        service.close()


def test_worker_once_records_success_with_no_network_when_rewriting_empty_db(tmp_path) -> None:
    service = AgentService(
        AppPaths(
            config_path=Path("config/watch_profiles.yaml"),
            db_path=tmp_path / "articles.sqlite",
            content_dir=tmp_path / "content",
        )
    )
    worker = AgentWorker(service, WorkerSettings(profile_id="all"))
    try:
        run_id, result_count = worker.run_once(RunAction.REWRITE_DIGESTS)
        runs = service.repo.list_runs()
    finally:
        service.close()

    assert result_count == 0
    assert runs[0]["id"] == run_id
    assert runs[0]["status"] == RunStatus.SUCCESS.value
