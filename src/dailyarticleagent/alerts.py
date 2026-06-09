from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Alert:
    title: str
    message: str
    level: str = "info"
    data: dict | None = None


class AlertManager:
    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url if webhook_url is not None else os.getenv("DAA_ALERT_WEBHOOK_URL", "").strip()

    def send(self, alert: Alert) -> None:
        log = LOGGER.error if alert.level == "error" else LOGGER.info
        log("%s: %s", alert.title, alert.message)
        if not self.webhook_url:
            return
        payload = {
            "title": alert.title,
            "message": alert.message,
            "level": alert.level,
            "data": alert.data or {},
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(self.webhook_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.warning("Alert webhook failed: %s", exc)
