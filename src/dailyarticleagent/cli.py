from __future__ import annotations

import sys
from pathlib import Path

import typer

from .archive import export_data, restore_data
from .config import load_profiles
from .llm import LlmClient, LlmSettings
from .models import FeedbackRating, RunAction, RunStatus
from .service import AgentService, AppPaths
from .worker import AgentWorker, WorkerSettings

app = typer.Typer(help="DailyArticleAgent literature radar.")
CONFIG_OPTION = typer.Option(
    None,
    help="Watch profile YAML path. Defaults to DAA_CONFIG_PATH or config/watch_profiles.yaml.",
)
DB_OPTION = typer.Option(None, help="SQLite database path. Defaults to DAA_DB_PATH or data/articles.sqlite.")
CONTENT_OPTION = typer.Option(None, help="Markdown content directory. Defaults to DAA_CONTENT_DIR or content.")
USE_LLM_OPTION = typer.Option(False, help="Call configured OpenAI-compatible LLM.")
EXPORT_PATH_ARGUMENT = typer.Argument(..., help="Output ZIP path.")
RESTORE_PATH_ARGUMENT = typer.Argument(..., help="Input ZIP path.")


def _service(config: Path | None, db: Path | None, content: Path | None, use_llm: bool) -> AgentService:
    return AgentService(AppPaths.from_env(config_path=config, db_path=db, content_dir=content), use_llm=use_llm)


@app.command()
def profiles(config: Path | None = CONFIG_OPTION) -> None:
    """List configured watch profiles."""
    for profile in load_profiles(AppPaths.from_env(config_path=config).config_path).values():
        typer.echo(f"{profile.id}\t{profile.name}\t{len(profile.sources)} sources")


@app.command()
def daily(
    profile: str = typer.Argument(..., help="Profile id, or 'all'."),
    fetch_lookback_days: int = typer.Option(
        3,
        help="Metadata fetch cushion; digest still covers only the target date.",
    ),
    config: Path | None = CONFIG_OPTION,
    db: Path | None = DB_OPTION,
    content: Path | None = CONTENT_OPTION,
    use_llm: bool = USE_LLM_OPTION,
) -> None:
    """Fetch papers, classify them, and write daily Markdown digest."""
    svc = _service(config, db, content, use_llm)
    try:
        run_id, result_count = svc.run_with_history(
            RunAction.DAILY,
            profile,
            options={"fetch_lookback_days": fetch_lookback_days},
        )
        typer.echo(f"Run {run_id} completed ({result_count} selected papers)")
    finally:
        svc.close()


@app.command()
def weekly(
    profile: str = typer.Argument(..., help="Profile id, or 'all'."),
    week_ending: str | None = typer.Option(
        None,
        help="Week end date. Any date is normalized to that ISO week's Sunday.",
    ),
    config: Path | None = CONFIG_OPTION,
    db: Path | None = DB_OPTION,
    content: Path | None = CONTENT_OPTION,
    use_llm: bool = USE_LLM_OPTION,
) -> None:
    """Build weekly digest from stored daily classifications, fetching if needed."""
    svc = _service(config, db, content, use_llm)
    try:
        run_id, result_count = svc.run_with_history(
            RunAction.WEEKLY,
            profile,
            options={"week_ending": week_ending} if week_ending else {},
        )
        typer.echo(f"Run {run_id} completed ({result_count} selected papers)")
    finally:
        svc.close()


@app.command("list-digests")
def list_digests(
    db: Path | None = DB_OPTION,
) -> None:
    """List generated digest records."""
    svc = _service(None, db, None, use_llm=False)
    try:
        for digest in svc.repo.list_digests():
            typer.echo(f"{digest['id']}\t{digest['period']}\t{digest['profile_id']}\t{digest['markdown_path']}")
    finally:
        svc.close()


@app.command("runs")
def runs(
    status: str | None = typer.Option(None, help="Filter by running, success, or failed."),
    limit: int = typer.Option(20, help="Maximum runs to print."),
    db: Path | None = DB_OPTION,
) -> None:
    """List agent run history."""
    svc = _service(None, db, None, use_llm=False)
    try:
        run_status = RunStatus(status) if status else None
        for run in svc.repo.list_runs(status=run_status, limit=limit):
            typer.echo(
                f"{run['id']}\t{run['status']}\t{run['action']}\t{run['profile_id']}\t"
                f"{run['started_at']}\t{run['result_count']}\t{run['error']}"
            )
    finally:
        svc.close()


@app.command("feedback")
def feedback(
    paper_uid: str = typer.Argument(..., help="Paper uid."),
    profile_id: str = typer.Argument(..., help="Profile id."),
    rating: str = typer.Argument(..., help="Feedback rating: up, down, save, or skip."),
    note: str = typer.Option("", help="Optional feedback note."),
    db: Path | None = DB_OPTION,
) -> None:
    """Record paper feedback used by future ranking."""
    svc = _service(None, db, None, use_llm=False)
    try:
        svc.record_feedback(paper_uid, profile_id, FeedbackRating(rating), note=note)
        typer.echo(f"Recorded {rating} feedback for {paper_uid} in {profile_id}")
    finally:
        svc.close()


@app.command("export-data")
def export_data_command(
    output_path: Path = EXPORT_PATH_ARGUMENT,
    config: Path | None = CONFIG_OPTION,
    db: Path | None = DB_OPTION,
    content: Path | None = CONTENT_OPTION,
) -> None:
    """Export config, SQLite database, and generated content to a ZIP archive."""
    paths = AppPaths.from_env(config_path=config, db_path=db, content_dir=content)
    exported = export_data(paths, output_path)
    typer.echo(f"Exported data archive to {exported}")


@app.command("restore-data")
def restore_data_command(
    archive_path: Path = RESTORE_PATH_ARGUMENT,
    replace: bool = typer.Option(False, help="Allow replacing existing config, database, and content paths."),
    config: Path | None = CONFIG_OPTION,
    db: Path | None = DB_OPTION,
    content: Path | None = CONTENT_OPTION,
) -> None:
    """Restore config, SQLite database, and generated content from a ZIP archive."""
    paths = AppPaths.from_env(config_path=config, db_path=db, content_dir=content)
    try:
        restore_data(paths, archive_path, replace=replace)
    except FileExistsError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(f"Restored data archive from {archive_path}")


@app.command("retry-failed-runs")
def retry_failed_runs(
    limit: int = typer.Option(10, help="Maximum failed runs to retry."),
    config: Path | None = CONFIG_OPTION,
    db: Path | None = DB_OPTION,
    content: Path | None = CONTENT_OPTION,
    use_llm: bool = USE_LLM_OPTION,
) -> None:
    """Retry recent failed runs from the run history."""
    svc = _service(config, db, content, use_llm)
    try:
        retried = svc.retry_failed_runs(limit=limit)
        typer.echo(f"Retried {len(retried)} runs")
        for run_id, result_count in retried:
            typer.echo(f"Run {run_id} completed ({result_count} selected papers)")
    finally:
        svc.close()


@app.command()
def reanalyze(
    profile: str = typer.Argument(..., help="Profile id, or 'all'."),
    limit: int = typer.Option(20, help="Maximum selected papers per profile to reanalyze."),
    include_existing: bool = typer.Option(False, help="Also overwrite papers that already have insights."),
    config: Path | None = CONFIG_OPTION,
    db: Path | None = DB_OPTION,
    content: Path | None = CONTENT_OPTION,
    use_llm: bool = USE_LLM_OPTION,
) -> None:
    """Backfill LLM paper insights for already indexed selected papers."""
    svc = _service(config, db, content, use_llm)
    try:
        try:
            run_id, count = svc.run_with_history(
                RunAction.REANALYZE,
                profile,
                options={"limit": limit, "include_existing": include_existing},
            )
            typer.echo(f"Run {run_id} reanalyzed {count} papers")
        except RuntimeError as exc:
            typer.echo(str(exc))
            raise typer.Exit(1) from exc
    finally:
        svc.close()


@app.command("rewrite-digests")
def rewrite_digests(
    profile: str = typer.Argument("all", help="Profile id, or 'all'."),
    config: Path | None = CONFIG_OPTION,
    db: Path | None = DB_OPTION,
    content: Path | None = CONTENT_OPTION,
) -> None:
    """Rewrite existing Markdown digests from stored paper insights without calling an LLM."""
    svc = _service(config, db, content, use_llm=False)
    try:
        run_id, count = svc.run_with_history(RunAction.REWRITE_DIGESTS, profile)
        typer.echo(f"Run {run_id} rewrote {count} digest files")
    finally:
        svc.close()


@app.command("worker")
def worker(
    profile: str = typer.Argument("all", help="Profile id, or 'all'."),
    once: bool = typer.Option(False, help="Run one action then exit."),
    action: str = typer.Option("daily", help="Action for --once: daily or weekly."),
    daily_time: str = typer.Option("23:30", help="Local daily generation time."),
    weekly_time: str = typer.Option("23:45", help="Local Sunday weekly generation time."),
    poll_seconds: int = typer.Option(60, help="Worker poll interval."),
    fetch_lookback_days: int = typer.Option(3, help="Daily metadata fetch cushion."),
    config: Path | None = CONFIG_OPTION,
    db: Path | None = DB_OPTION,
    content: Path | None = CONTENT_OPTION,
    use_llm: bool = USE_LLM_OPTION,
) -> None:
    """Run the built-in scheduler/worker."""
    svc = _service(config, db, content, use_llm)
    settings = WorkerSettings(
        profile_id=profile,
        daily_time=daily_time,
        weekly_time=weekly_time,
        poll_seconds=poll_seconds,
        fetch_lookback_days=fetch_lookback_days,
    )
    agent_worker = AgentWorker(svc, settings=settings)
    try:
        if once:
            run_id, result_count = agent_worker.run_once(RunAction(action))
            typer.echo(f"Run {run_id} completed ({result_count} selected papers)")
            return
        typer.echo("DailyArticleAgent worker started. Press Ctrl+C to stop.")
        agent_worker.run_forever()
    finally:
        svc.close()


@app.command("llm-check")
def llm_check() -> None:
    """Check configured OpenAI-compatible LLM connectivity without printing secrets."""
    client = LlmClient(LlmSettings.from_env(enabled_override=True))
    typer.echo(f"API base: {client.settings.api_base}")
    typer.echo(f"Chat URL: {client.chat_completions_url}")
    typer.echo(f"Model: {client.settings.model}")
    try:
        models = client.list_models()
        typer.echo("Models: " + (", ".join(models[:20]) if models else "<not returned>"))
    except Exception as exc:
        typer.echo(f"Models check failed: {exc}")
    try:
        typer.echo(f"Chat check: {client.check_chat()}")
    except Exception as exc:
        typer.echo(f"Chat check failed: {exc}")
        raise typer.Exit(1) from exc


@app.command("schedule-help")
def schedule_help(
    profile: str = typer.Argument("all", help="Profile id, or 'all'."),
    daily_time: str = typer.Option("23:30", help="Local daily generation time."),
    weekly_time: str = typer.Option("23:45", help="Local Sunday weekly generation time."),
    use_llm: bool = USE_LLM_OPTION,
) -> None:
    """Print OS scheduler commands for automatic daily and weekly runs."""
    python_exe = Path(sys.executable).resolve()
    cwd = Path.cwd().resolve()
    llm_flag = " --use-llm" if use_llm else ""
    daily_args = f"-m dailyarticleagent.cli daily {profile}{llm_flag}"
    weekly_args = f"-m dailyarticleagent.cli weekly {profile}{llm_flag}"
    typer.echo("Windows Task Scheduler PowerShell:")
    typer.echo(_task_scheduler_command("DailyArticleAgent Daily", python_exe, cwd, daily_args, "Daily", daily_time))
    typer.echo(
        _task_scheduler_command(
            "DailyArticleAgent Weekly",
            python_exe,
            cwd,
            weekly_args,
            "Weekly -DaysOfWeek Sunday",
            weekly_time,
        )
    )
    typer.echo("")
    typer.echo("cron:")
    daily_hour, daily_minute = _split_time(daily_time)
    weekly_hour, weekly_minute = _split_time(weekly_time)
    typer.echo(
        f'{daily_minute} {daily_hour} * * * cd "{cwd}" '
        f'&& "{python_exe}" -m dailyarticleagent.cli daily {profile}{llm_flag}'
    )
    typer.echo(
        f'{weekly_minute} {weekly_hour} * * 0 cd "{cwd}" '
        f'&& "{python_exe}" -m dailyarticleagent.cli weekly {profile}{llm_flag}'
    )


def _split_time(value: str) -> tuple[str, str]:
    try:
        hour, minute = value.split(":", 1)
    except ValueError:
        raise typer.BadParameter("Use HH:MM time format") from None
    if not hour.isdigit() or not minute.isdigit():
        raise typer.BadParameter("Use HH:MM time format")
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise typer.BadParameter("Use HH:MM time format")
    return str(int(hour)), str(int(minute))


def _task_scheduler_command(
    task_name: str,
    python_exe: Path,
    cwd: Path,
    args: str,
    trigger: str,
    at_time: str,
) -> str:
    action = (
        "New-ScheduledTaskAction "
        f"-Execute '{python_exe}' "
        f"-Argument '{args}' "
        f"-WorkingDirectory '{cwd}'"
    )
    task_trigger = f"New-ScheduledTaskTrigger -{trigger} -At {at_time}"
    return (
        "$action = "
        f"{action}; $trigger = {task_trigger}; "
        f"Register-ScheduledTask -TaskName '{task_name}' -Action $action -Trigger $trigger -Force"
    )


if __name__ == "__main__":
    app()
