from __future__ import annotations

import json
from typing import Any

import pytest

from subscription_gateway.config import CodexSettings
from subscription_gateway.errors import ProviderError
from subscription_gateway.providers import codex as codex_module
from subscription_gateway.providers.codex import CodexProvider, parse_codex_result
from subscription_gateway.providers.process import ProcessResult


def test_codex_response_normalization() -> None:
    lines = [
        {"type": "thread.started", "thread_id": "thread-123"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "normalized answer"},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 12,
                "cached_input_tokens": 3,
                "output_tokens": 5,
            },
        },
    ]
    result = ProcessResult(0, "\n".join(json.dumps(line) for line in lines), "progress")
    response = parse_codex_result(result)
    assert response.text == "normalized answer"
    assert response.provider_session_id == "thread-123"
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 5
    assert len(response.raw_events) == 4


def test_codex_malformed_output_is_protocol_error() -> None:
    with pytest.raises(ProviderError) as caught:
        parse_codex_result(ProcessResult(0, "not-json", ""))
    assert caught.value.code == "provider_malformed_output"


def test_codex_command_is_argument_array_and_resume_aware() -> None:
    provider = CodexProvider(CodexSettings(command="/bin/echo"))
    initial = provider.build_command(
        session_id=None,
        model="gpt-5.6-sol",
        prompt="user data; $(whoami)",
        permissions="read-only",
    )
    resumed = provider.build_command(
        session_id="thread-123",
        model="gpt-5.6-sol",
        prompt="continue",
        permissions="workspace-write",
    )
    assert initial[0] == "/bin/echo"
    assert initial[-1] == "user data; $(whoami)"
    assert initial[initial.index("--sandbox") + 1] == "read-only"
    assert resumed[1:3] == ["exec", "resume"]
    assert "thread-123" in resumed


@pytest.mark.asyncio
async def test_codex_timeout_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CodexProvider(CodexSettings(command="/bin/echo"))

    async def timeout(*args: Any, **kwargs: Any) -> ProcessResult:
        raise TimeoutError

    monkeypatch.setattr(codex_module, "run_process", timeout)
    with pytest.raises(ProviderError) as caught:
        await provider.send(
            None,
            "gpt-5.6-sol",
            [{"role": "user", "content": "hello"}],
            {},
        )
    assert caught.value.error_type == "provider_timeout"
    assert caught.value.status_code == 504
