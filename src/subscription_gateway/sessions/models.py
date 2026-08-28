"""Persistent session model."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ProviderSession(BaseModel):
    gateway_session_id: str
    provider: str
    provider_session_id: str | None = None
    model: str
    provider_model: str
    session_kind: Literal["chat", "agent"] = "chat"
    working_directory: str | None = None
    permissions: Literal["read-only", "workspace-write"] = "read-only"
    created_at: datetime
    last_used_at: datetime
