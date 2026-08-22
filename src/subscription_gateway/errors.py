"""Normalized errors shared by providers and HTTP compatibility layers."""

from __future__ import annotations

from typing import Any


class GatewayError(Exception):
    """An error safe to expose through the local gateway API."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        code: str,
        status_code: int,
        provider: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.code = code
        self.status_code = status_code
        self.provider = provider
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "message": self.message,
            "type": self.error_type,
            "code": self.code,
        }
        if self.provider is not None:
            error["provider"] = self.provider
        return {"error": error}


class ProviderError(GatewayError):
    """A normalized provider failure."""


def invalid_request(message: str, code: str = "invalid_request") -> GatewayError:
    return GatewayError(message, error_type="invalid_request", code=code, status_code=400)


def model_not_available(model: str, provider: str | None = None) -> GatewayError:
    return GatewayError(
        f"Model '{model}' is not available.",
        error_type="model_not_available",
        code="model_not_available",
        status_code=404,
        provider=provider,
    )


def session_not_found(session_id: str) -> GatewayError:
    return GatewayError(
        f"Gateway session '{session_id}' was not found.",
        error_type="session_not_found",
        code="session_not_found",
        status_code=404,
    )


def agent_permission_error(message: str) -> GatewayError:
    return GatewayError(
        message,
        error_type="agent_permission_error",
        code="agent_permission_error",
        status_code=403,
    )


def provider_unavailable(provider: str) -> ProviderError:
    return ProviderError(
        f"{provider_display_name(provider)} is unavailable or not ready.",
        error_type="provider_unavailable",
        code="provider_unavailable",
        status_code=503,
        provider=provider,
        retryable=True,
    )


def provider_not_authenticated(provider: str) -> ProviderError:
    return ProviderError(
        f"{provider_display_name(provider)} is not authenticated. "
        "Authenticate with the official client first.",
        error_type="provider_not_authenticated",
        code="provider_not_authenticated",
        status_code=503,
        provider=provider,
        retryable=True,
    )


def provider_display_name(provider: str) -> str:
    return {"codex": "Codex", "claude": "Claude Code"}.get(provider, provider)
