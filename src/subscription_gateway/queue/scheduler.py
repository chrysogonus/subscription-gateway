"""Per-provider semaphores with queue-delay accounting."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class ProviderScheduler:
    def __init__(self, limits: dict[str, int]) -> None:
        self._semaphores = {
            provider: asyncio.Semaphore(limit) for provider, limit in limits.items()
        }
        self._waiting: defaultdict[str, int] = defaultdict(int)
        self._inflight: defaultdict[str, int] = defaultdict(int)

    @asynccontextmanager
    async def slot(self, provider: str) -> AsyncIterator[float]:
        semaphore = self._semaphores.setdefault(provider, asyncio.Semaphore(1))
        started = time.monotonic()
        self._waiting[provider] += 1
        if semaphore.locked():
            logger.info(
                "request queued provider=%s waiting=%d inflight=%d",
                provider,
                self._waiting[provider],
                self._inflight[provider],
            )
        try:
            await semaphore.acquire()
        except BaseException:
            self._waiting[provider] -= 1
            raise
        self._waiting[provider] -= 1
        self._inflight[provider] += 1
        delay = time.monotonic() - started
        try:
            yield delay
        finally:
            self._inflight[provider] -= 1
            semaphore.release()

    def status(self) -> dict[str, dict[str, int]]:
        return {
            provider: {
                "waiting": self._waiting[provider],
                "inflight": self._inflight[provider],
            }
            for provider in self._semaphores
        }
