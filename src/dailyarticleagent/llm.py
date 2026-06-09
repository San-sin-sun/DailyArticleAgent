from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

JSON_INVALID_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')


@dataclass(frozen=True)
class LlmSettings:
    enabled: bool
    api_base: str
    api_key: str
    model: str
    chat_completions_url: str | None = None

    @classmethod
    def from_env(cls, enabled_override: bool | None = None) -> LlmSettings:
        env_enabled = os.getenv("DAA_LLM_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        api_base = os.getenv("DAA_LLM_API_BASE", "").strip().rstrip("/")
        return cls(
            enabled=env_enabled if enabled_override is None else enabled_override,
            api_base=_normalize_openai_base(api_base) if api_base else "",
            api_key=os.getenv("DAA_LLM_API_KEY", ""),
            model=os.getenv("DAA_LLM_MODEL", ""),
            chat_completions_url=os.getenv("DAA_LLM_CHAT_COMPLETIONS_URL") or None,
        )


class LlmClient:
    def __init__(self, settings: LlmSettings | None = None) -> None:
        self.settings = settings or LlmSettings.from_env()

    def summarize(self, system: str, user: str) -> str | None:
        content = self.complete(system, user)
        return content.strip() if content else None

    def summarize_json(self, system: str, user: str) -> dict[str, Any] | None:
        content = self.complete(system, user)
        if not content:
            return None
        return _load_json_object(content)

    def complete(self, system: str, user: str) -> str | None:
        if not self.settings.enabled:
            return None
        if not self.settings.api_key:
            raise RuntimeError("DAA_LLM_ENABLED is true but DAA_LLM_API_KEY is empty")
        if not self.settings.model:
            raise RuntimeError("DAA_LLM_ENABLED is true but DAA_LLM_MODEL is empty")
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                self.chat_completions_url,
                json=payload,
                headers=headers,
            )
            _raise_for_status(response)
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    @property
    def chat_completions_url(self) -> str:
        if self.settings.chat_completions_url:
            return self.settings.chat_completions_url
        if not self.settings.api_base:
            raise RuntimeError("DAA_LLM_API_BASE is empty")
        return f"{self.settings.api_base}/chat/completions"

    @property
    def models_url(self) -> str:
        if not self.settings.api_base:
            raise RuntimeError("DAA_LLM_API_BASE is empty")
        return f"{self.settings.api_base}/models"

    def list_models(self) -> list[str]:
        if not self.settings.api_key:
            raise RuntimeError("DAA_LLM_API_KEY is empty")
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        with httpx.Client(timeout=30.0) as client:
            response = client.get(self.models_url, headers=headers)
            _raise_for_status(response)
            data = response.json()
        models = data.get("data", data)
        if not isinstance(models, list):
            return []
        result = []
        for item in models:
            if isinstance(item, dict) and item.get("id"):
                result.append(str(item["id"]))
            elif isinstance(item, str):
                result.append(item)
        return result

    def check_chat(self) -> str:
        result = self.summarize("Return a tiny health check.", "Reply with exactly: ok")
        return result or ""


def _load_json_object(content: str) -> dict[str, Any]:
    candidate = content
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        candidate = _json_candidate(content)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            data = json.loads(_escape_invalid_json_backslashes(candidate))
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")
    return data


def _json_candidate(content: str) -> str:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found", content, 0)
    return content[start : end + 1]


def _escape_invalid_json_backslashes(value: str) -> str:
    return JSON_INVALID_ESCAPE.sub(r"\\\\", value)


def _normalize_openai_base(value: str) -> str:
    if value.endswith("/v1"):
        return value
    if value.endswith("/chat/completions"):
        return value.removesuffix("/chat/completions")
    return f"{value}/v1"


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = _safe_response_text(response)
        raise RuntimeError(
            f"LLM request failed: {response.status_code} {response.reason_phrase} "
            f"for {response.request.url}. Response body: {body}"
        ) from exc


def _safe_response_text(response: httpx.Response, limit: int = 1000) -> str:
    text = response.text.strip()
    if not text:
        return "<empty>"
    return text[:limit]
