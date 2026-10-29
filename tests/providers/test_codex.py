from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from subscription_gateway.config import CodexSettings
from subscription_gateway.errors import GatewayError, ProviderError
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


def test_codex_rejected_model_is_classified_as_model_not_available() -> None:
    """Verbatim message from `codex exec --model <not-on-plan>`. If the CLI
    rewords this, the failure is misclassified as retryable and the request
    silently falls back to another provider."""

    event = {
        "type": "turn.failed",
        "error": {
            "message": (
                '{"type":"error","status":400,"error":{"type":"invalid_request_error",'
                '"message":"The \'gpt-9\' model is not supported when using Codex '
                'with a ChatGPT account."}}'
            )
        },
    }
    with pytest.raises(ProviderError) as caught:
        parse_codex_result(ProcessResult(1, json.dumps(event), ""))
    assert caught.value.code == "model_not_available"


def test_codex_command_is_argument_array_and_resume_aware() -> None:
    provider = CodexProvider(CodexSettings(command="/bin/echo"))
    initial = provider.build_command(
        session_id=None,
        model="gpt-5.6-sol",
        permissions="read-only",
    )
    resumed = provider.build_command(
        session_id="thread-123",
        model="gpt-5.6-sol",
        permissions="workspace-write",
    )
    assert initial[0] == "/bin/echo"
    assert initial[-1] == "-"  # the prompt is read from stdin
    assert "--ignore-user-config" in initial
    assert initial[initial.index("--sandbox") + 1] == "read-only"
    assert resumed[1:3] == ["exec", "resume"]
    assert "--ignore-user-config" in resumed
    assert 'sandbox_mode="workspace-write"' in resumed
    assert resumed[-2:] == ["thread-123", "-"]


def test_codex_is_not_exposed_as_a_filesystem_agent() -> None:
    provider = CodexProvider(CodexSettings(command="/bin/echo"))
    assert provider.capabilities.filesystem_agent is False


def test_codex_invalid_working_directory_does_not_fall_back(tmp_path: Path) -> None:
    provider = CodexProvider(CodexSettings(command="/bin/echo"))
    missing = tmp_path / "missing"
    with pytest.raises(NotADirectoryError, match="working directory is unavailable"):
        provider._working_directory({"cwd": str(missing)})


@pytest.mark.asyncio
async def test_codex_invalid_working_directory_is_normalized(tmp_path: Path) -> None:
    provider = CodexProvider(
        CodexSettings(command="/bin/echo", working_directory=tmp_path / "missing")
    )
    with pytest.raises(ProviderError) as caught:
        await provider.send(None, "gpt-5.6-sol", [{"role": "user", "content": "hi"}], {})
    assert caught.value.code == "provider_unavailable"


def test_codex_command_rejects_invalid_permissions() -> None:
    provider = CodexProvider(CodexSettings(command="/bin/echo"))
    with pytest.raises(GatewayError) as caught:
        provider.build_command(
            session_id="thread-123",
            model="gpt-5.6-sol",
            permissions='read-only"; sandbox_mode="danger-full-access',
        )
    assert caught.value.code == "invalid_permissions"


def test_codex_command_rejects_flag_like_model() -> None:
    """A provider_model replayed from storage reaches argv without other checks."""

    provider = CodexProvider(CodexSettings(command="/bin/echo"))
    with pytest.raises(GatewayError) as caught:
        provider.build_command(
            session_id=None,
            model="--sandbox",
            permissions="read-only",
        )
    assert caught.value.code == "invalid_model_name"
    assert caught.value.status_code == 400


def test_codex_command_accepts_dotted_model() -> None:
    provider = CodexProvider(CodexSettings(command="/bin/echo"))
    command = provider.build_command(
        session_id=None,
        model="us.openai.gpt-5.6-sol",
        permissions="read-only",
    )
    assert command[command.index("--model") + 1] == "us.openai.gpt-5.6-sol"


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "subscription"),
    [("Logged in using ChatGPT", True), ("Logged in using an API key - sk-***", False)],
)
async def test_codex_login_status_reports_the_auth_method(
    monkeypatch: pytest.MonkeyPatch, output: str, subscription: bool
) -> None:
    provider = CodexProvider(CodexSettings(command="/bin/echo"))

    async def status(*args: Any, **kwargs: Any) -> ProcessResult:
        return ProcessResult(0, output, "")

    monkeypatch.setattr(codex_module, "run_process", status)
    assert await provider.is_authenticated()
    assert provider.subscription_auth is subscription


# Far over the 128 KiB Linux limit on one argv string, which used to break long chats.
LONG_MESSAGE = "x" * (300 * 1024)


@pytest.mark.asyncio
async def test_codex_sends_the_prompt_on_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_run_process(command: list[str], **kwargs: Any) -> ProcessResult:
        calls.append({"command": command, **kwargs})
        events = [
            {"type": "thread.started", "thread_id": "t"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
        ]
        return ProcessResult(0, "\n".join(json.dumps(event) for event in events), "")

    monkeypatch.setattr(codex_module, "run_process", fake_run_process)
    provider = CodexProvider(CodexSettings(command="/bin/echo", working_directory=tmp_path))
    response = await provider.send(
        None, "gpt-5.6-sol", [{"role": "user", "content": LONG_MESSAGE}], {}
    )

    assert response.text == "done"
    assert calls[0]["stdin_text"] == f"[USER]\n{LONG_MESSAGE}"
    assert calls[0]["command"][-1] == "-"
    assert all(LONG_MESSAGE not in part for part in calls[0]["command"])
