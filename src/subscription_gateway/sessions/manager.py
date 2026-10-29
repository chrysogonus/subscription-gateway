"""Session lifecycle and provider-thread binding."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import timedelta
from typing import Literal

from subscription_gateway.errors import invalid_request, session_not_found
from subscription_gateway.sessions.models import ProviderSession
from subscription_gateway.sessions.storage import SQLiteSessionStorage, utc_now


class SessionManager:
    def __init__(
        self,
        storage: SQLiteSessionStorage,
        *,
        session_retention_days: int | None = 30,
    ) -> None:
        self.storage = storage
        self.session_retention_days = session_retention_days
        self._session_locks: dict[str, _SessionLock] = {}
        self._session_locks_guard = asyncio.Lock()
        self._cleanup_lock = asyncio.Lock()
        self._last_cleanup = 0.0

    async def require(self, gateway_session_id: str) -> ProviderSession:
        session = await self.storage.get(gateway_session_id)
        if session is None:
            raise session_not_found(gateway_session_id)
        # Expired rows linger until the next cleanup; they must not be resumable meanwhile.
        days = self.session_retention_days
        if days is not None and session.last_used_at < utc_now() - timedelta(days=days):
            raise session_not_found(gateway_session_id)
        return session

    async def require_compatible(
        self,
        gateway_session_id: str,
        requested_model: str,
        *,
        session_kind: Literal["chat", "agent"] = "chat",
        working_directory: str | None = None,
        permissions: Literal["read-only", "workspace-write"] = "read-only",
    ) -> ProviderSession:
        session = await self.require(gateway_session_id)
        if requested_model not in {session.model, "subscription/auto"}:
            raise invalid_request(
                "A gateway session cannot change models. Start a new session instead.",
                code="session_model_mismatch",
            )
        if (
            session.session_kind != session_kind
            or session.working_directory != working_directory
            or session.permissions != permissions
        ):
            raise invalid_request(
                "A gateway session cannot change API type, working directory, or permissions. "
                "Start a new session instead.",
                code="session_context_mismatch",
            )
        return session

    async def create(
        self,
        *,
        provider: str,
        model: str,
        provider_model: str,
        provider_session_id: str | None = None,
        session_kind: Literal["chat", "agent"] = "chat",
        working_directory: str | None = None,
        permissions: Literal["read-only", "workspace-write"] = "read-only",
    ) -> ProviderSession:
        await self.cleanup_expired()
        now = utc_now()
        session = ProviderSession(
            gateway_session_id=str(uuid.uuid4()),
            provider=provider,
            provider_session_id=provider_session_id,
            model=model,
            provider_model=provider_model,
            session_kind=session_kind,
            working_directory=working_directory,
            permissions=permissions,
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

    @asynccontextmanager
    async def serialized(self, gateway_session_id: str) -> AsyncIterator[None]:
        async with self._session_locks_guard:
            entry = self._session_locks.setdefault(gateway_session_id, _SessionLock())
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._session_locks_guard:
                entry.users -= 1
                if entry.users == 0:
                    self._session_locks.pop(gateway_session_id, None)

    async def cleanup_expired(self, *, force: bool = False) -> int:
        if self.session_retention_days is None:
            return 0
        now = time.monotonic()
        if not force and now - self._last_cleanup < 3600:
            return 0
        async with self._cleanup_lock:
            now = time.monotonic()
            if not force and now - self._last_cleanup < 3600:
                return 0
            cutoff = utc_now() - timedelta(days=self.session_retention_days)
            deleted = await self.storage.delete_older_than(cutoff)
            self._last_cleanup = now
            return deleted


@dataclass(slots=True)
class _SessionLock:
    lock: asyncio.Lock = dataclass_field(default_factory=asyncio.Lock)
    users: int = 0
