from __future__ import annotations

from pathlib import Path

import pytest

from subscription_gateway.sessions.manager import SessionManager
from subscription_gateway.sessions.storage import SQLiteSessionStorage


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


@pytest.mark.asyncio
async def test_missing_session_raises_normalized_error(tmp_path: Path) -> None:
    storage = SQLiteSessionStorage(tmp_path / "sessions.db")
    await storage.initialize()
    manager = SessionManager(storage)
    with pytest.raises(Exception) as caught:
        await manager.require("missing")
    await storage.close()
    assert caught.value.code == "session_not_found"
