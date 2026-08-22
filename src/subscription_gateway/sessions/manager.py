"""Session lifecycle and provider-thread binding."""

from __future__ import annotations

import uuid

from subscription_gateway.errors import invalid_request, session_not_found
from subscription_gateway.sessions.models import ProviderSession
from subscription_gateway.sessions.storage import SQLiteSessionStorage, utc_now


class SessionManager:
    def __init__(self, storage: SQLiteSessionStorage) -> None:
        self.storage = storage

    async def require(self, gateway_session_id: str) -> ProviderSession:
        session = await self.storage.get(gateway_session_id)
        if session is None:
            raise session_not_found(gateway_session_id)
        return session

    async def require_compatible(
        self, gateway_session_id: str, requested_model: str
    ) -> ProviderSession:
        session = await self.require(gateway_session_id)
        if requested_model not in {session.model, "subscription/auto"}:
            raise invalid_request(
                "A gateway session cannot change models. Start a new session instead.",
                code="session_model_mismatch",
            )
        return session

    async def create(
        self,
        *,
        provider: str,
        model: str,
        provider_model: str,
        provider_session_id: str | None = None,
    ) -> ProviderSession:
        now = utc_now()
        session = ProviderSession(
            gateway_session_id=str(uuid.uuid4()),
            provider=provider,
            provider_session_id=provider_session_id,
            model=model,
            provider_model=provider_model,
            created_at=now,
            last_used_at=now,
        )
        await self.storage.put(session)
        return session

    async def update(
        self,
        session: ProviderSession,
        *,
        provider_session_id: str | None = None,
        provider: str | None = None,
        provider_model: str | None = None,
        clear_provider_session: bool = False,
    ) -> ProviderSession:
        next_provider_session = (
            None if clear_provider_session else provider_session_id or session.provider_session_id
        )
        updated = session.model_copy(
            update={
                "provider": provider or session.provider,
                "provider_model": provider_model or session.provider_model,
                "provider_session_id": next_provider_session,
                "last_used_at": utc_now(),
            }
        )
        await self.storage.put(updated)
        return updated
