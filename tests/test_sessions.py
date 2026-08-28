from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from subscription_gateway.errors import GatewayError
from subscription_gateway.sessions.manager import SessionManager
from subscription_gateway.sessions.storage import SQLiteSessionStorage, utc_now


@pytest.mark.asyncio
async def test_session_persists_across_storage_reopen(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    first_storage = SQLiteSessionStorage(path)
    await first_storage.initialize()
    session = await SessionManager(first_storage).create(
        provider="codex",
        model="codex/gpt-5.6-sol",
        provider_model="gpt-5.6-sol",
        provider_session_id="thread-1",
    )
    await first_storage.close()

    second_storage = SQLiteSessionStorage(path)
    await second_storage.initialize()
    restored = await second_storage.get(session.gateway_session_id)
    await second_storage.close()

    assert restored is not None
    assert restored.provider_session_id == "thread-1"
    assert restored.provider == "codex"
    assert restored.session_kind == "chat"
    assert restored.working_directory is None
    assert restored.permissions == "read-only"


@pytest.mark.asyncio
async def test_missing_session_raises_normalized_error(tmp_path: Path) -> None:
    storage = SQLiteSessionStorage(tmp_path / "sessions.db")
    await storage.initialize()
    manager = SessionManager(storage)
    with pytest.raises(GatewayError) as caught:
        await manager.require("missing")
    await storage.close()
    assert caught.value.code == "session_not_found"


@pytest.mark.asyncio
async def test_legacy_database_is_migrated_in_place(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE provider_sessions (
            gateway_session_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_session_id TEXT,
            model TEXT NOT NULL,
            provider_model TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT NOT NULL
        )
        """
    )
    now = utc_now().isoformat()
    connection.execute(
        "INSERT INTO provider_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("legacy", "codex", "thread", "codex/model", "model", now, now),
    )
    connection.commit()
    connection.close()

    storage = SQLiteSessionStorage(path)
    await storage.initialize()
    restored = await storage.get("legacy")
    await storage.close()

    assert restored is not None
    assert restored.session_kind == "chat"
    assert restored.working_directory is None
    assert restored.permissions == "read-only"


@pytest.mark.asyncio
async def test_expired_sessions_are_deleted(tmp_path: Path) -> None:
    storage = SQLiteSessionStorage(tmp_path / "sessions.db")
    await storage.initialize()
    manager = SessionManager(storage, session_retention_days=30)
    session = await manager.create(
        provider="codex",
        model="codex/gpt-5.6-sol",
        provider_model="gpt-5.6-sol",
    )
    expired = session.model_copy(update={"last_used_at": utc_now() - timedelta(days=31)})
    await storage.put(expired)

    assert await manager.cleanup_expired(force=True) == 1
    assert await storage.get(session.gateway_session_id) is None
    await storage.close()


@pytest.mark.asyncio
async def test_same_session_operations_are_serialized(tmp_path: Path) -> None:
    storage = SQLiteSessionStorage(tmp_path / "sessions.db")
    manager = SessionManager(storage)
    active = 0
    max_active = 0

    async def operation() -> None:
        nonlocal active, max_active
        async with manager.serialized("same-session"):
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(operation(), operation(), operation())
    assert max_active == 1
