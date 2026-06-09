from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime

from .alerts import Alert, AlertManager
from .models import RunAction
from .service import AgentService, local_today


@dataclass(frozen=True)
class WorkerSettings:
    profile_id: str = "all"
    daily_time: str = "23:30"
    weekly_time: str = "23:45"
    weekly_day: int = 6
    poll_seconds: int = 60
    fetch_lookback_days: int = 3


class AgentWorker:
    def __init__(
        self,
        service: AgentService,
        settings: WorkerSettings | None = None,
        alerts: AlertManager | None = None,
    ) -> None:
        self.service = service
        self.settings = settings or WorkerSettings()
        self.alerts = alerts or AlertManager()
        self._last_daily: date | None = None
        self._last_weekly: date | None = None

    def run_once(self, action: RunAction = RunAction.DAILY) -> tuple[int, int]:
        return self._run(action)

    def run_forever(self) -> None:
        while True:
            now = datetime.now().astimezone()
            today = local_today(now)
            if self._should_run_daily(now, today):
                self._run(RunAction.DAILY)
                self._last_daily = today
            if self._should_run_weekly(now, today):
                self._run(RunAction.WEEKLY)
                self._last_weekly = today
            time.sleep(max(1, self.settings.poll_seconds))

    def _run(self, action: RunAction) -> tuple[int, int]:
        options = {}
        if action == RunAction.DAILY:
            options["fetch_lookback_days"] = self.settings.fetch_lookback_days
        try:
            run_id, result_count = self.service.run_with_history(action, self.settings.profile_id, options=options)
        except Exception as exc:
            self.alerts.send(
                Alert(
                    title=f"DailyArticleAgent {action.value} failed",
                    message=str(exc),
                    level="error",
                    data={"action": action.value, "profile_id": self.settings.profile_id},
                )
            )
            raise
        self.alerts.send(
            Alert(
                title=f"DailyArticleAgent {action.value} finished",
                message=f"Run {run_id} completed with {result_count} selected papers.",
                data={"run_id": run_id, "result_count": result_count, "profile_id": self.settings.profile_id},
            )
        )
        return run_id, result_count

    def _should_run_daily(self, now: datetime, today: date) -> bool:
        return self._time_reached(now, self.settings.daily_time) and self._last_daily != today

    def _should_run_weekly(self, now: datetime, today: date) -> bool:
        return (
            now.weekday() == self.settings.weekly_day
            and self._time_reached(now, self.settings.weekly_time)
            and self._last_weekly != today
        )

    @staticmethod
    def _time_reached(now: datetime, value: str) -> bool:
        hour, minute = _split_time(value)
        return (now.hour, now.minute) >= (hour, minute)


def _split_time(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)
