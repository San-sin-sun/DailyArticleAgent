from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .classifier import classify_all_papers, classify_papers
from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_CONTENT_DIR,
    DEFAULT_DB_PATH,
    load_profiles,
    resolve_config_path,
    resolve_runtime_path,
)
from .digest import build_daily_digest, build_weekly_digest, write_digest
from .llm import LlmClient, LlmSettings
from .models import (
    ClassifiedPaper,
    Digest,
    DigestPeriod,
    FeedbackRating,
    PaperFeedback,
    PaperInsight,
    RunAction,
    RunStatus,
    WatchProfile,
)
from .sources import SourceRegistry
from .storage import Repository


@dataclass(frozen=True)
class AppPaths:
    config_path: Path = DEFAULT_CONFIG_PATH
    db_path: Path = DEFAULT_DB_PATH
    content_dir: Path = DEFAULT_CONTENT_DIR

    @classmethod
    def from_env(
        cls,
        config_path: Path | None = None,
        db_path: Path | None = None,
        content_dir: Path | None = None,
    ) -> AppPaths:
        load_dotenv()
        return cls(
            config_path=resolve_config_path(config_path),
            db_path=resolve_runtime_path(db_path, "DAA_DB_PATH", DEFAULT_DB_PATH),
            content_dir=resolve_runtime_path(content_dir, "DAA_CONTENT_DIR", DEFAULT_CONTENT_DIR),
        )


class AgentService:
    def __init__(self, paths: AppPaths | None = None, use_llm: bool = False) -> None:
        load_dotenv()
        self.paths = paths or AppPaths.from_env()
        self.profiles = load_profiles(self.paths.config_path)
        self.repo = Repository(self.paths.db_path)
        self.sources = SourceRegistry()
        self.llm = LlmClient(LlmSettings.from_env(enabled_override=True)) if use_llm else None

    def close(self) -> None:
        self.repo.close()

    def profile(self, profile_id: str) -> WatchProfile:
        try:
            return self.profiles[profile_id]
        except KeyError as exc:
            known = ", ".join(sorted(self.profiles))
            raise KeyError(f"Unknown profile '{profile_id}'. Known profiles: {known}") from exc

    def run_daily(
        self,
        profile_id: str,
        today: date | None = None,
        fetch_lookback_days: int = 3,
    ) -> Digest:
        profile = self.profile(profile_id)
        target = today or local_today()
        fetch_start = target - timedelta(days=fetch_lookback_days)
        raw_papers = self.sources.fetch(profile.sources, fetch_start, target)
        seen = self.repo.seen_profile_uids(profile.id, (paper.uid for paper in raw_papers))
        candidates = [
            paper
            for paper in raw_papers
            if paper.published_at == target or paper.uid not in seen
        ]
        classified = classify_all_papers(
            profile,
            candidates,
            feedback_adjustments=self.repo.feedback_adjustments(profile.id),
        )
        self.repo.save_papers(raw_papers)
        self.repo.save_classifications(classified)
        selected = self.repo.daily_classifications(profile, target, profile.max_items)
        digest = build_daily_digest(profile, selected, target, target, self.paths.content_dir, self.llm)
        write_digest(digest)
        self.repo.save_digest(digest)
        return digest

    def run_weekly(
        self,
        profile_id: str,
        week_ending: date | None = None,
        fetch_if_missing: bool = True,
    ) -> Digest:
        profile = self.profile(profile_id)
        start, end = weekly_window(week_ending or previous_complete_week_end())
        selected = self.repo.latest_daily_classifications(
            profile,
            start,
            end,
            profile.max_items * 3,
        )
        if not selected and fetch_if_missing:
            raw_papers = self.sources.fetch(profile.sources, start, end)
            weekly_papers = [
                paper
                for paper in raw_papers
                if start <= (paper.published_at or paper.discovered_at.date()) <= end
            ]
            selected = classify_papers(
                profile,
                weekly_papers,
                feedback_adjustments=self.repo.feedback_adjustments(profile.id),
            )
            self.repo.save_papers([item.paper for item in selected])
            self.repo.save_classifications(selected)
        digest = build_weekly_digest(
            profile,
            selected[: profile.max_items * 2],
            start,
            end,
            self.paths.content_dir,
            self.llm,
        )
        write_digest(digest)
        self.repo.save_digest(digest)
        return digest

    def run_all_daily(self, fetch_lookback_days: int = 3) -> list[Digest]:
        return [
            self.run_daily(profile_id, fetch_lookback_days=fetch_lookback_days)
            for profile_id in self.profiles
        ]

    def run_all_weekly(self, week_ending: date | None = None) -> list[Digest]:
        return [
            self.run_weekly(profile_id, week_ending=week_ending)
            for profile_id in self.profiles
        ]

    def reanalyze(
        self,
        profile_id: str,
        limit: int = 20,
        missing_insights_only: bool = True,
    ) -> int:
        if not self.llm:
            raise RuntimeError("reanalyze requires --use-llm so the agent can read and judge papers")
        profile = self.profile(profile_id)
        selected = self.repo.selected_classifications(
            profile,
            limit=limit,
            missing_insights_only=missing_insights_only,
        )
        if not selected:
            return 0
        today = local_today()
        digest = build_daily_digest(profile, selected, today, today, self.paths.content_dir, self.llm)
        self.repo.save_paper_insights(digest.paper_insights)
        self.rewrite_digests(profile_id=profile.id)
        return len(digest.paper_insights)

    def reanalyze_all(self, limit: int = 20, missing_insights_only: bool = True) -> dict[str, int]:
        return {
            profile_id: self.reanalyze(profile_id, limit=limit, missing_insights_only=missing_insights_only)
            for profile_id in self.profiles
        }

    def rewrite_digests(self, profile_id: str | None = None) -> int:
        rewritten = 0
        for row in self.repo.list_digests():
            if profile_id and row["profile_id"] != profile_id:
                continue
            profile = self.profile(row["profile_id"])
            start = date.fromisoformat(row["start_date"])
            end = date.fromisoformat(row["end_date"])
            period = DigestPeriod(row["period"])
            if period == DigestPeriod.DAILY:
                selected = self.repo.latest_daily_classifications(profile, start, end, profile.max_items)
                digest = build_daily_digest(
                    profile,
                    selected,
                    start,
                    end,
                    self.paths.content_dir,
                    stored_insights=self._stored_insights(profile.id, selected),
                )
            else:
                selected = self.repo.latest_daily_classifications(profile, start, end, profile.max_items * 3)[
                    : profile.max_items * 2
                ]
                digest = build_weekly_digest(
                    profile,
                    selected,
                    start,
                    end,
                    self.paths.content_dir,
                    stored_insights=self._stored_insights(profile.id, selected),
                )
            write_digest(digest)
            self.repo.save_digest(digest)
            rewritten += 1
        return rewritten

    def _stored_insights(self, profile_id: str, selected: list[ClassifiedPaper]) -> list[PaperInsight]:
        return self.repo.paper_insights_for_profile(profile_id, (item.paper.uid for item in selected))

    def record_feedback(self, paper_uid: str, profile_id: str, rating: FeedbackRating, note: str = "") -> None:
        self.repo.save_feedback(
            PaperFeedback(
                paper_uid=paper_uid,
                profile_id=profile_id,
                rating=rating,
                note=note,
            )
        )

    def run_with_history(
        self,
        action: RunAction,
        profile_id: str,
        options: dict | None = None,
        parent_run_id: int | None = None,
        attempts: int = 1,
    ) -> tuple[int, int]:
        options = options or {}
        run_id = self.repo.start_run(
            action,
            profile_id,
            options=options,
            parent_run_id=parent_run_id,
            attempts=attempts,
        )
        try:
            result_count = self._execute_run_action(action, profile_id, options)
        except Exception as exc:
            self.repo.finish_run(run_id, RunStatus.FAILED, error=str(exc))
            raise
        self.repo.finish_run(run_id, RunStatus.SUCCESS, result_count=result_count)
        return run_id, result_count

    def retry_run(self, run_id: int) -> tuple[int, int]:
        run = self.repo.get_run(run_id)
        if not run:
            raise KeyError(f"Unknown run id: {run_id}")
        if run["status"] != RunStatus.FAILED.value:
            raise ValueError(f"Run {run_id} is not failed")
        return self.run_with_history(
            RunAction(run["action"]),
            run["profile_id"],
            options=run["options"],
            parent_run_id=run_id,
            attempts=int(run["attempts"]) + 1,
        )

    def retry_failed_runs(self, limit: int = 10) -> list[tuple[int, int]]:
        retried: list[tuple[int, int]] = []
        for run in reversed(self.repo.list_runs(status=RunStatus.FAILED, limit=limit)):
            retried.append(self.retry_run(int(run["id"])))
        return retried

    def _execute_run_action(self, action: RunAction, profile_id: str, options: dict) -> int:
        if action == RunAction.DAILY:
            fetch_lookback_days = int(options.get("fetch_lookback_days", 3))
            digests = (
                self.run_all_daily(fetch_lookback_days=fetch_lookback_days)
                if profile_id == "all"
                else [self.run_daily(profile_id, fetch_lookback_days=fetch_lookback_days)]
            )
            return sum(len(digest.papers) for digest in digests)
        if action == RunAction.WEEKLY:
            week_ending_value = options.get("week_ending")
            week_ending = date.fromisoformat(week_ending_value) if week_ending_value else None
            digests = (
                self.run_all_weekly(week_ending=week_ending)
                if profile_id == "all"
                else [self.run_weekly(profile_id, week_ending=week_ending)]
            )
            return sum(len(digest.papers) for digest in digests)
        if action == RunAction.REANALYZE:
            limit = int(options.get("limit", 20))
            include_existing = bool(options.get("include_existing", False))
            if profile_id == "all":
                return sum(self.reanalyze_all(limit=limit, missing_insights_only=not include_existing).values())
            return self.reanalyze(profile_id, limit=limit, missing_insights_only=not include_existing)
        if action == RunAction.REWRITE_DIGESTS:
            return self.rewrite_digests(profile_id=None if profile_id == "all" else profile_id)
        raise ValueError(f"Unsupported run action: {action}")


def weekly_window(week_ending: date) -> tuple[date, date]:
    end = week_ending
    if end.weekday() != 6:
        end = end + timedelta(days=6 - end.weekday())
    return end - timedelta(days=6), end


def previous_complete_week_end(today: date | None = None) -> date:
    current = today or local_today()
    days_since_sunday = (current.weekday() + 1) % 7
    if days_since_sunday == 0:
        return current
    return current - timedelta(days=days_since_sunday)


def local_today(now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    timezone_name = os.getenv("DAA_TIMEZONE", "")
    if timezone_name:
        try:
            return current.astimezone(ZoneInfo(timezone_name)).date()
        except ZoneInfoNotFoundError:
            pass
    return current.astimezone().date()
