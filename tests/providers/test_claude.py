from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from subscription_gateway.config import ClaudeSettings
from subscription_gateway.errors import GatewayError, ProviderError
from subscription_gateway.providers import claude as claude_module
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
            "cache_creation_input_tokens": 5,
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
    # Writing to the cache is not a cache hit.
    assert response.usage.cached_input_tokens == 2


def test_claude_usage_limit_is_normalized() -> None:
    with pytest.raises(ProviderError) as caught:
        parse_claude_result(ProcessResult(1, "", "subscription usage limit reached"))
    assert caught.value.error_type == "provider_usage_limit"
    assert caught.value.status_code == 429


def test_claude_rejected_model_is_classified_as_model_not_available() -> None:
    """Verbatim message from `claude --print --model <unknown>`. If the CLI
    rewords this, the failure is misclassified as retryable and the request
    silently falls back to another provider."""

    payload = {
        "is_error": True,
        "subtype": "success",
        "api_error_status": 404,
        "result": (
            "There's an issue with the selected model (gpt-9). It may not exist "
            "or you may not have access to it. Run --model to pick a different model."
        ),
    }
    with pytest.raises(ProviderError) as caught:
        parse_claude_result(ProcessResult(0, json.dumps(payload), ""))
    assert caught.value.code == "model_not_available"


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
    assert "--restricted" in command
    assert "--strict-mcp-config" in command
    assert command[command.index("--tools") + 1] == "Read,Glob,Grep"
    assert command[command.index("--allowedTools") + 1] == "Read,Glob,Grep"


def test_claude_write_agent_is_restricted_to_file_tools() -> None:
    provider = ClaudeProvider(ClaudeSettings(command="/bin/echo"))
    command = provider.build_command(
        session_id=None,
        model="opus",
        prompt="edit",
        permissions="workspace-write",
        agent_task=True,
    )
    assert "--restricted" in command
    assert "--strict-mcp-config" in command
    assert command[command.index("--tools") + 1] == "Read,Glob,Grep,Edit,Write"
    assert "Bash" not in command


def test_claude_invalid_working_directory_does_not_fall_back(tmp_path: Path) -> None:
    provider = ClaudeProvider(ClaudeSettings(command="/bin/echo"))
    missing = tmp_path / "missing"
    with pytest.raises(NotADirectoryError, match="working directory is unavailable"):
        provider._working_directory({"cwd": str(missing)})


@pytest.mark.asyncio
async def test_claude_invalid_working_directory_is_normalized(tmp_path: Path) -> None:
    provider = ClaudeProvider(
        ClaudeSettings(command="/bin/echo", working_directory=tmp_path / "missing")
    )
    with pytest.raises(ProviderError) as caught:
        await provider.send(None, "opus", [{"role": "user", "content": "hi"}], {})
    assert caught.value.code == "provider_unavailable"


def test_claude_command_rejects_invalid_permissions() -> None:
    provider = ClaudeProvider(ClaudeSettings(command="/bin/echo"))
    with pytest.raises(GatewayError) as caught:
        provider.build_command(
            session_id=None,
            model="opus",
            prompt="hi",
            permissions="bypassPermissions",
            agent_task=True,
        )
    assert caught.value.code == "invalid_permissions"


def test_claude_command_rejects_flag_like_model() -> None:
    """A provider_model replayed from storage reaches argv without other checks."""

    provider = ClaudeProvider(ClaudeSettings(command="/bin/echo"))
    with pytest.raises(GatewayError) as caught:
        provider.build_command(
            session_id=None,
            model="--dangerously-skip-permissions",
            prompt="hi",
            permissions="read-only",
            agent_task=False,
        )
    assert caught.value.code == "invalid_model_name"
    assert caught.value.status_code == 400


def test_claude_command_accepts_full_model_name() -> None:
    provider = ClaudeProvider(ClaudeSettings(command="/bin/echo"))
    command = provider.build_command(
        session_id=None,
        model="claude-fable-5",
        prompt="hi",
        permissions="read-only",
        agent_task=False,
    )
    assert command[command.index("--model") + 1] == "claude-fable-5"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "subscription"),
    [
        ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}, True),
        ({"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"}, False),
        ({"loggedIn": True, "authMethod": "none", "apiProvider": "bedrock"}, False),
    ],
)
async def test_claude_auth_status_reports_the_auth_method(
    monkeypatch: pytest.MonkeyPatch, status: dict[str, Any], subscription: bool
) -> None:
    provider = ClaudeProvider(ClaudeSettings(command="/bin/echo"))

    async def auth_status(*args: Any, **kwargs: Any) -> ProcessResult:
        return ProcessResult(0, json.dumps(status), "")

    monkeypatch.setattr(claude_module, "run_process", auth_status)
    assert await provider.is_authenticated()
    assert provider.subscription_auth is subscription
