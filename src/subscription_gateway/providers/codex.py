"""Codex provider using the documented non-interactive JSONL CLI interface."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from subscription_gateway.compat.openai_chat import messages_to_prompt
from subscription_gateway.config import CodexSettings
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


class CodexProvider(Provider):
    name = "codex"
    display_name = "Codex"
    capabilities = ProviderCapabilities(
        chat=True,
        streaming=True,
        persistent_sessions=True,
        filesystem_agent=False,
        tools=True,
    )

    def __init__(self, settings: CodexSettings) -> None:
        super().__init__(configured_models(settings.models), settings.default_alias)
        self.settings = settings
        self._executable = shutil.which(settings.command)
        self._availability: tuple[float, bool] | None = None

    def is_installed(self) -> bool:
        return self._executable is not None

    async def is_authenticated(self) -> bool:
        if not self._executable:
            return False
        try:
            result = await run_process(
                [self._executable, "login", "status"],
                cwd=self._working_directory(),
                timeout_seconds=min(10.0, self.settings.timeout_seconds),
            )
        except (OSError, TimeoutError):
            return False
        output = f"{result.stdout}\n{result.stderr}".lower()
        self.subscription_auth = "api key" not in output
        return result.returncode == 0 and "logged in" in output and "not logged in" not in output

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
            raise NotADirectoryError(f"Codex working directory is unavailable: {path}")
        return path

    def build_command(
        self,
        *,
        session_id: str | None,
        model: str,
        permissions: str,
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
                "Codex permissions must be read-only or workspace-write.",
                code="invalid_permissions",
            )
        if session_id and not session_id.startswith("pending:"):
            return [
                self._executable,
                "exec",
                "resume",
                "--json",
                "--model",
                model,
                "--ignore-user-config",
                "--skip-git-repo-check",
                "-c",
                f'sandbox_mode="{permissions}"',
                session_id,
                "-",
            ]
        return [
            self._executable,
            "exec",
            "--json",
            "--color",
            "never",
            "--model",
            model,
            "--ignore-user-config",
            "--sandbox",
            permissions,
            "--skip-git-repo-check",
            # The prompt goes on stdin: Linux caps one argv string at 128 KiB.
            "-",
        ]

    async def send(
        self,
        session_id: str | None,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> ProviderResponse:
        if not self.settings.enabled or not self._executable:
            raise ProviderError(
                "Codex is not installed or is disabled.",
                error_type="provider_unavailable",
                code="provider_unavailable",
                status_code=503,
                provider=self.name,
                retryable=True,
            )
        prompt = messages_to_prompt(messages)
        permissions = str(options.get("permissions", "read-only"))
        if permissions not in {"read-only", "workspace-write"}:
            permissions = "read-only"
        command = self.build_command(
            session_id=session_id,
            model=model,
            permissions=permissions,
        )
        try:
            result = await run_process(
                command,
                cwd=self._working_directory(options),
                timeout_seconds=self.settings.timeout_seconds,
                stdin_text=prompt,
            )
        except TimeoutError as exc:
            raise ProviderError(
                "Codex command timed out.",
                error_type="provider_timeout",
                code="provider_timeout",
                status_code=504,
                provider=self.name,
                retryable=True,
            ) from exc
        except OSError as exc:
            raise ProviderError(
                "Codex could not be started.",
                error_type="provider_unavailable",
                code="provider_unavailable",
                status_code=503,
                provider=self.name,
                retryable=True,
            ) from exc
        return parse_codex_result(result)


def parse_codex_result(result: ProcessResult) -> ProviderResponse:
    events: list[dict[str, Any]] = []
    messages: list[str] = []
    session_id: str | None = None
    usage = ProviderUsage()
    provider_diagnostic = result.stderr

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "Codex returned malformed JSONL output.",
                error_type="provider_protocol_error",
                code="provider_malformed_output",
                status_code=502,
                provider="codex",
                retryable=True,
            ) from exc
        if not isinstance(event, dict):
            continue
        events.append(event)
        event_type = event.get("type")
        if event_type == "thread.started":
            session_id = str(event.get("thread_id") or "") or session_id
        elif event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                messages.append(item["text"])
        elif event_type == "turn.completed":
            raw_usage = event.get("usage") or {}
            usage = ProviderUsage(
                input_tokens=int(raw_usage.get("input_tokens") or 0),
                output_tokens=int(raw_usage.get("output_tokens") or 0),
                cached_input_tokens=int(raw_usage.get("cached_input_tokens") or 0),
            )
        elif event_type in {"turn.failed", "error"}:
            provider_diagnostic += "\n" + json.dumps(event)

    if result.returncode != 0:
        raise classify_provider_failure("codex", provider_diagnostic)
    if not messages:
        if provider_diagnostic.strip():
            raise classify_provider_failure("codex", provider_diagnostic)
        raise ProviderError(
            "Codex completed without an assistant message.",
            error_type="provider_protocol_error",
            code="provider_missing_output",
            status_code=502,
            provider="codex",
            retryable=True,
        )
    return ProviderResponse(
        text="\n\n".join(messages),
        provider_session_id=session_id,
        usage=usage,
        raw_events=events,
    )
