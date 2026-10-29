"""Claude Code provider using its supported print-mode JSON interface."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from subscription_gateway.compat.openai_chat import messages_to_prompt
from subscription_gateway.config import ClaudeSettings
from subscription_gateway.errors import ProviderError, invalid_request
from subscription_gateway.model_names import is_valid_provider_model
from subscription_gateway.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderResponse,
    ProviderUsage,
    configured_models,
)
from subscription_gateway.providers.process import (
    ProcessResult,
    classify_provider_failure,
    run_process,
)

# Agent runs pass --restricted and --strict-mcp-config, documented as needing this release.
MIN_AGENT_VERSION = (2, 1, 248)


def format_version(version: tuple[int, ...]) -> str:
    return ".".join(map(str, version))


class ClaudeProvider(Provider):
    name = "claude"
    display_name = "Claude Code"
    capabilities = ProviderCapabilities(
        chat=True,
        streaming=True,
        persistent_sessions=True,
        filesystem_agent=True,
        tools=True,
    )

    def __init__(self, settings: ClaudeSettings) -> None:
        super().__init__(configured_models(settings.models), settings.default_alias)
        self.settings = settings
        self._executable = shutil.which(settings.command)
        self._availability: tuple[float, bool] | None = None
        self._version: tuple[int, ...] | None = None

    def is_installed(self) -> bool:
        return self._executable is not None

    async def is_authenticated(self) -> bool:
        if not self._executable:
            return False
        try:
            result = await run_process(
                [self._executable, "auth", "status"],
                cwd=self._working_directory(),
                timeout_seconds=min(10.0, self.settings.timeout_seconds),
            )
        except (OSError, TimeoutError):
            return False
        if result.returncode != 0:
            return False
        self.subscription_auth = True
        try:
            status = json.loads(result.stdout)
        except json.JSONDecodeError:
            return "logged in" in f"{result.stdout}\n{result.stderr}".lower()
        if not isinstance(status, dict):
            return False
        # Unknown methods count as a subscription so the sharing warning errs on the safe side.
        self.subscription_auth = (
            status.get("authMethod") != "api_key"
            and status.get("apiProvider", "firstParty") == "firstParty"
        )
        return bool(status.get("loggedIn"))

    async def version(self) -> tuple[int, ...] | None:
        """The installed CLI's version, or None when it cannot be determined."""

        # shortcut: cached for the process lifetime, so a CLI upgrade needs a gateway restart.
        if self._version is None and self._executable:
            try:
                result = await run_process(
                    [self._executable, "--version"],
                    cwd=self._working_directory(),
                    timeout_seconds=min(10.0, self.settings.timeout_seconds),
                )
            except (OSError, TimeoutError):
                return None
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
            if result.returncode == 0 and match:
                self._version = tuple(int(part) for part in match.groups())
        return self._version

    async def is_available(self) -> bool:
        now = time.monotonic()
        if self._availability and now - self._availability[0] < 10.0:
            return self._availability[1]
        available = self.settings.enabled and self.is_installed() and await self.is_authenticated()
        self._availability = (now, available)
        return available

    async def list_models(self) -> list[str]:
        if self.settings.advertise_unavailable or await self.is_available():
            return list(self.models)
        return []

    def _working_directory(self, options: dict[str, Any] | None = None) -> Path:
        requested = (options or {}).get("cwd")
        path = Path(requested).expanduser() if requested else self.settings.working_directory
        if not path.is_dir():
            raise NotADirectoryError(f"Claude working directory is unavailable: {path}")
        return path

    def build_command(
        self,
        *,
        session_id: str | None,
        model: str,
        prompt: str,
        permissions: str,
        agent_task: bool,
    ) -> list[str]:
        if not self._executable:
            raise classify_provider_failure(self.name, "unavailable")
        # Also covers provider_model values replayed from a stored session, which
        # reach argv without passing through config or routing validation.
        if not is_valid_provider_model(model):
            raise invalid_request(
                f"Model name '{model}' is not a valid provider model.",
                code="invalid_model_name",
            )
        if permissions not in {"read-only", "workspace-write"}:
            raise invalid_request(
                "Claude permissions must be read-only or workspace-write.",
                code="invalid_permissions",
            )
        command = [
            self._executable,
            "--print",
            "--output-format",
            "json",
            "--safe-mode",
            "--model",
            model,
        ]
        if session_id and not session_id.startswith("pending:"):
            command.extend(["--resume", session_id])
        if agent_task:
            command.extend(["--restricted", "--strict-mcp-config"])
            if permissions == "workspace-write":
                tools = "Read,Glob,Grep,Edit,Write"
                command.extend(
                    [
                        "--tools",
                        tools,
                        "--allowedTools",
                        tools,
                        "--permission-mode",
                        "acceptEdits",
                    ]
                )
            else:
                tools = "Read,Glob,Grep"
                command.extend(
                    [
                        "--tools",
                        tools,
                        "--allowedTools",
                        tools,
                        "--permission-mode",
                        "plan",
                    ]
                )
        else:
            command.extend(["--tools", "", "--permission-mode", "plan"])
        command.append(prompt)
        return command

    async def send(
        self,
        session_id: str | None,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> ProviderResponse:
        if not self.settings.enabled or not self._executable:
            raise ProviderError(
                "Claude Code is not installed or is disabled.",
                error_type="provider_unavailable",
                code="provider_unavailable",
                status_code=503,
                provider=self.name,
                retryable=True,
            )
        if options.get("agent_task"):
            version = await self.version()
            # An unknown version runs anyway: a failed probe should not block a working CLI.
            if version is not None and version < MIN_AGENT_VERSION:
                raise invalid_request(
                    f"Claude Code {format_version(version)} cannot run agent tasks; "
                    f"{format_version(MIN_AGENT_VERSION)} or newer is required.",
                    code="unsupported_provider_capability",
                )
        permissions = str(options.get("permissions", "read-only"))
        if permissions not in {"read-only", "workspace-write"}:
            permissions = "read-only"
        command = self.build_command(
            session_id=session_id,
            model=model,
            prompt=messages_to_prompt(messages),
            permissions=permissions,
            agent_task=bool(options.get("agent_task")),
        )
        try:
            result = await run_process(
                command,
                cwd=self._working_directory(options),
                timeout_seconds=self.settings.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderError(
                "Claude Code command timed out.",
                error_type="provider_timeout",
                code="provider_timeout",
                status_code=504,
                provider=self.name,
                retryable=True,
            ) from exc
        except OSError as exc:
            raise ProviderError(
                "Claude Code could not be started.",
                error_type="provider_unavailable",
                code="provider_unavailable",
                status_code=503,
                provider=self.name,
                retryable=True,
            ) from exc
        return parse_claude_result(result)


def parse_claude_result(result: ProcessResult) -> ProviderResponse:
    if result.returncode != 0:
        raise classify_provider_failure("claude", f"{result.stdout}\n{result.stderr}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "Claude Code returned malformed JSON output.",
            error_type="provider_protocol_error",
            code="provider_malformed_output",
            status_code=502,
            provider="claude",
            retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderError(
            "Claude Code returned an unexpected JSON value.",
            error_type="provider_protocol_error",
            code="provider_malformed_output",
            status_code=502,
            provider="claude",
            retryable=True,
        )
    if payload.get("is_error") or payload.get("subtype") in {"error", "failed"}:
        raise classify_provider_failure("claude", json.dumps(payload))
    text = payload.get("result")
    if not isinstance(text, str):
        structured = payload.get("structured_output")
        text = json.dumps(structured, ensure_ascii=False) if structured is not None else None
    if not text:
        raise ProviderError(
            "Claude Code completed without an assistant result.",
            error_type="provider_protocol_error",
            code="provider_missing_output",
            status_code=502,
            provider="claude",
            retryable=True,
        )
    raw_usage = payload.get("usage") or {}
    usage = ProviderUsage(
        input_tokens=int(raw_usage.get("input_tokens") or 0),
        output_tokens=int(raw_usage.get("output_tokens") or 0),
        cached_input_tokens=int(raw_usage.get("cache_read_input_tokens") or 0),
    )
    session_id = payload.get("session_id")
    return ProviderResponse(
        text=text,
        provider_session_id=str(session_id) if session_id else None,
        usage=usage,
        raw_events=[payload],
    )
