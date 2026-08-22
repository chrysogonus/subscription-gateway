"""Small SQLite store containing metadata only, never provider credentials."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from subscription_gateway.sessions.models import ProviderSession

SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_sessions (
    gateway_session_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_session_id TEXT,
    model TEXT NOT NULL,
    provider_model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL
)
"""


class SQLiteSessionStorage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if str(self.path) != ":memory:":
            await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        async with self._lock:
            if self._connection is None:
                self._connection = await asyncio.to_thread(
                    sqlite3.connect, str(self.path), check_same_thread=False
                )
                self._connection.row_factory = sqlite3.Row
                await asyncio.to_thread(self._connection.execute, SCHEMA)
                await asyncio.to_thread(self._connection.commit)

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                await asyncio.to_thread(self._connection.close)
                self._connection = None

    def _connection_or_raise(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("session storage has not been initialized")
        return self._connection

    async def put(self, session: ProviderSession) -> None:
        values = (
            session.gateway_session_id,
            session.provider,
            session.provider_session_id,
            session.model,
            session.provider_model,
            session.created_at.isoformat(),
            session.last_used_at.isoformat(),
        )
        async with self._lock:
            connection = self._connection_or_raise()
            await asyncio.to_thread(
                connection.execute,
                """
                INSERT INTO provider_sessions (
                    gateway_session_id, provider, provider_session_id, model,
                    provider_model, created_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gateway_session_id) DO UPDATE SET
                    provider=excluded.provider,
                    provider_session_id=excluded.provider_session_id,
                    model=excluded.model,
                    provider_model=excluded.provider_model,
                    last_used_at=excluded.last_used_at
                """,
                values,
            )
            await asyncio.to_thread(connection.commit)

    async def get(self, gateway_session_id: str) -> ProviderSession | None:
        async with self._lock:
            connection = self._connection_or_raise()
            cursor = await asyncio.to_thread(
                connection.execute,
                "SELECT * FROM provider_sessions WHERE gateway_session_id = ?",
                (gateway_session_id,),
            )
            row = await asyncio.to_thread(cursor.fetchone)
        return None if row is None else self._from_row(row)

    async def delete(self, gateway_session_id: str) -> None:
        async with self._lock:
            connection = self._connection_or_raise()
            await asyncio.to_thread(
                connection.execute,
                "DELETE FROM provider_sessions WHERE gateway_session_id = ?",
                (gateway_session_id,),
            )
            await asyncio.to_thread(connection.commit)

    async def count(self) -> int:
        async with self._lock:
            connection = self._connection_or_raise()
            cursor = await asyncio.to_thread(
                connection.execute, "SELECT COUNT(*) FROM provider_sessions"
            )
            row = await asyncio.to_thread(cursor.fetchone)
        return int(row[0])

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ProviderSession:
        values: dict[str, Any] = dict(row)
        values["created_at"] = datetime.fromisoformat(values["created_at"])
        values["last_used_at"] = datetime.fromisoformat(values["last_used_at"])
        return ProviderSession.model_validate(values)


def utc_now() -> datetime:
    return datetime.now(UTC)
