from __future__ import annotations

import httpx
import pytest

from dailyarticleagent.llm import LlmClient, LlmSettings, _load_json_object, _raise_for_status


def test_llm_base_accepts_provider_host_without_v1(monkeypatch) -> None:
    monkeypatch.setenv("DAA_LLM_API_BASE", "https://llm.example.test")

    settings = LlmSettings.from_env(enabled_override=True)

    assert settings.enabled is True
    assert settings.api_base == "https://llm.example.test/v1"


def test_llm_base_accepts_full_chat_completions_path(monkeypatch) -> None:
    monkeypatch.setenv("DAA_LLM_API_BASE", "https://llm.example.test/v1/chat/completions")

    settings = LlmSettings.from_env(enabled_override=True)

    assert settings.api_base == "https://llm.example.test/v1"


def test_llm_accepts_explicit_chat_completions_url(monkeypatch) -> None:
    monkeypatch.setenv("DAA_LLM_CHAT_COMPLETIONS_URL", "https://llm.example.test/chat/completions")

    client = LlmClient(LlmSettings.from_env(enabled_override=True))

    assert client.chat_completions_url == "https://llm.example.test/chat/completions"


def test_llm_http_error_includes_response_body() -> None:
    request = httpx.Request("POST", "https://llm.example.test/v1/chat/completions")
    response = httpx.Response(400, request=request, text='{"error":"model is invalid"}')

    with pytest.raises(RuntimeError, match="model is invalid"):
        _raise_for_status(response)


def test_load_json_object_accepts_wrapped_response() -> None:
    data = _load_json_object('Here is the JSON:\n{"chinese_summary": "ok"}\n')

    assert data == {"chinese_summary": "ok"}


def test_load_json_object_recovers_latex_backslashes() -> None:
    data = _load_json_object('{"content_analysis": "uses \\epsilon and \\mathcal{F} notation"}')

    assert data["content_analysis"] == r"uses \epsilon and \mathcal{F} notation"
