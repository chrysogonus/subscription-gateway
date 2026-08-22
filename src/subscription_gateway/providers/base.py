"""Normalized provider contract and response models."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    chat: bool = True
    streaming: bool = False
    persistent_sessions: bool = False
    filesystem_agent: bool = False
    tools: bool = False


class ProviderUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def openai_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.input_tokens,
            "completion_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


class ProviderResponse(BaseModel):
    text: str
    provider_session_id: str | None = None
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    finish_reason: str = "stop"
    raw_events: list[dict[str, Any]] = Field(default_factory=list, exclude=True)


class ProviderEvent(BaseModel):
    type: Literal["session", "delta", "completed"]
    text: str | None = None
    session_id: str | None = None
    response: ProviderResponse | None = None


class Provider(ABC):
    name: str
    display_name: str
    capabilities: ProviderCapabilities

    def __init__(self, models: dict[str, str], default_alias: str | None = None) -> None:
        self.models = models
        # An alias that is not in this catalog degrades to the first entry rather
        # than failing later in default_model(); `None in models` is False.
        self.default_alias = default_alias if default_alias in models else None

    def provider_model(self, public_model: str) -> str | None:
        return self.models.get(public_model)

    def default_model(self) -> tuple[str, str] | None:
        if self.default_alias is not None:
            return self.default_alias, self.models[self.default_alias]
        return next(iter(self.models.items()), None)

    @abstractmethod
    async def is_available(self) -> bool: ...

    @abstractmethod
    async def is_authenticated(self) -> bool: ...

    @abstractmethod
    def is_installed(self) -> bool: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    async def create_session(self, model: str) -> str:
        """Return a lazy marker; real runtimes create their session on first send."""

        return f"pending:{uuid.uuid4()}"

    @abstractmethod
    async def send(
        self,
        session_id: str | None,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> ProviderResponse: ...

    async def stream(
        self,
        session_id: str | None,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> AsyncIterator[ProviderEvent]:
        """Valid coarse streaming fallback for runtimes without token deltas."""

        response = await self.send(session_id, model, messages, options)
        if response.provider_session_id:
            yield ProviderEvent(type="session", session_id=response.provider_session_id)
        if response.text:
            yield ProviderEvent(type="delta", text=response.text)
        yield ProviderEvent(type="completed", response=response)


def configured_models(settings_models: dict[str, Any]) -> dict[str, str]:
    return {alias: settings.provider_model for alias, settings in settings_models.items()}
