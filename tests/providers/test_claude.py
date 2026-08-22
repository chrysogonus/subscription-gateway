from __future__ import annotations

import json

import pytest

from subscription_gateway.config import ClaudeSettings
from subscription_gateway.errors import ProviderError
from subscription_gateway.providers.claude import ClaudeProvider, parse_claude_result
from subscription_gateway.providers.process import ProcessResult


def test_claude_subprocess_parsing() -> None:
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "Claude answer",
        "session_id": "42c5f7a2-98bf-4f0a-b86f-53ad6d42e059",
        "usage": {
            "input_tokens": 8,
            "output_tokens": 3,
            "cache_read_input_tokens": 2,
        },
    }
    response = parse_claude_result(ProcessResult(0, json.dumps(payload), "diagnostics"))
    assert response.text == "Claude answer"
    assert response.provider_session_id == payload["session_id"]
    assert response.usage.openai_dict() == {
        "prompt_tokens": 8,
        "completion_tokens": 3,
        "total_tokens": 11,
    }


def test_claude_usage_limit_is_normalized() -> None:
    with pytest.raises(ProviderError) as caught:
        parse_claude_result(ProcessResult(1, "", "subscription usage limit reached"))
    assert caught.value.error_type == "provider_usage_limit"
    assert caught.value.status_code == 429


def test_claude_command_disables_tools_for_chat() -> None:
    provider = ClaudeProvider(ClaudeSettings(command="/bin/echo"))
    command = provider.build_command(
        session_id=None,
        model="opus",
        prompt="hello && touch /tmp/nope",
        permissions="read-only",
        agent_task=False,
    )
    assert command[0] == "/bin/echo"
    assert command[-1] == "hello && touch /tmp/nope"
    assert "--safe-mode" in command
    assert command[command.index("--tools") + 1] == ""
    assert "--print" in command


def test_claude_command_resumes_session() -> None:
    provider = ClaudeProvider(ClaudeSettings(command="/bin/echo"))
    command = provider.build_command(
        session_id="42c5f7a2-98bf-4f0a-b86f-53ad6d42e059",
        model="opus",
        prompt="continue",
        permissions="read-only",
        agent_task=True,
    )
    assert command[command.index("--resume") + 1] == "42c5f7a2-98bf-4f0a-b86f-53ad6d42e059"
    assert command[command.index("--allowedTools") + 1] == "Read,Glob,Grep"
