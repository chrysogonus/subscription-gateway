"""Persistent session model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProviderSession(BaseModel):
    gateway_session_id: str
    provider: str
    provider_session_id: str | None = None
    model: str
    provider_model: str
    created_at: datetime
    last_used_at: datetime
