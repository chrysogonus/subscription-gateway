"""Cancellation-safe subprocess execution without a shell."""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from subscription_gateway.errors import ProviderError, invalid_request, provider_display_name


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
        return
    except TimeoutError:
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    await process.wait()


async def run_process(
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    stdin_text: str | None = None,
) -> ProcessResult:
    """Run an argument array and always reap the child on timeout or cancellation."""

    # Encode before spawning: a failure after the child starts would leave it running.
    try:
        stdin_bytes = None if stdin_text is None else stdin_text.encode()
    except UnicodeEncodeError as exc:
        raise invalid_request(
            "The request contains text that is not valid Unicode (an unpaired surrogate).",
            code="request_validation_error",
        ) from exc
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(stdin_bytes),
            timeout=timeout_seconds,
        )
    except (TimeoutError, asyncio.CancelledError):
        await asyncio.shield(_terminate_process(process))
        raise
    return ProcessResult(
        returncode=process.returncode or 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


def classify_provider_failure(provider: str, diagnostic: str) -> ProviderError:
    """Map diagnostics without reflecting potentially sensitive stderr to callers."""

    text = diagnostic.lower()
    display = provider_display_name(provider)
    if any(
        marker in text
        for marker in (
            "not logged in",
            "not authenticated",
            "please login",
            "please log in",
            "unauthorized",
            "authentication required",
            "invalid api key",
        )
    ):
        return ProviderError(
            f"{display} is not authenticated. Authenticate with the official client first.",
            error_type="provider_not_authenticated",
            code="provider_not_authenticated",
            status_code=503,
            provider=provider,
        )
    if any(marker in text for marker in ("rate limit", "usage limit", "quota", "exhausted")):
        return ProviderError(
            f"{display} subscription usage limit reached.",
            error_type="provider_usage_limit",
            code="provider_usage_limit",
            status_code=429,
            provider=provider,
            retryable=True,
        )
    if any(
        marker in text
        for marker in (
            "model not found",
            "unknown model",
            "unsupported model",
            "model is not available",
            "invalid model",
            # Observed wording. Codex, for a model outside the account's plan:
            # "The 'x' model is not supported when using Codex with a ChatGPT account."
            "model is not supported",
            # Claude, for an unknown or inaccessible model: "There's an issue with
            # the selected model (x). It may not exist or you may not have access to it."
            "issue with the selected model",
            "may not have access to it",
        )
    ):
        return ProviderError(
            f"The requested model is not available through {display}.",
            error_type="model_not_available",
            code="model_not_available",
            status_code=404,
            provider=provider,
            retryable=True,
        )
    if any(marker in text for marker in ("temporarily unavailable", "overloaded", "try again")):
        return ProviderError(
            f"{display} is temporarily unavailable.",
            error_type="provider_unavailable",
            code="provider_temporary_error",
            status_code=503,
            provider=provider,
            retryable=True,
        )
    return ProviderError(
        f"{display} failed to complete the request.",
        error_type="provider_protocol_error",
        code="provider_execution_failed",
        status_code=502,
        provider=provider,
        retryable=True,
    )
