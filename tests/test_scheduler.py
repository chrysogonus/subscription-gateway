from __future__ import annotations

import asyncio

import pytest

from subscription_gateway.queue.scheduler import ProviderScheduler


@pytest.mark.asyncio
async def test_provider_queue_enforces_limit() -> None:
    scheduler = ProviderScheduler({"codex": 1})
    active = 0
    max_active = 0

    async def worker() -> None:
        nonlocal active, max_active
        async with scheduler.slot("codex"):
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(4)))
    assert max_active == 1
    assert scheduler.status()["codex"] == {"waiting": 0, "inflight": 0}
