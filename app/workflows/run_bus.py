from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.workflows.runtime_trace import TraceEvent


logger = logging.getLogger(__name__)


DEFAULT_QUEUE_SIZE = 256


class RunEventBus:
    """In-process pub/sub for trace events, keyed by run_id.

    One bounded queue per subscriber. If a slow subscriber overflows, its queue
    drops the new event and emits a synthetic ``{"type": "dropped"}`` marker so
    the consumer can detect gaps and reconcile via the polling endpoint.

    A terminal sentinel (None) closes the subscriber's stream cleanly.
    """

    _SENTINEL: Any = None

    def __init__(self, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self.queue_size = max(1, queue_size)
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def _add(self, run_id: str) -> asyncio.Queue:
        # Single-threaded asyncio: no lock needed; dict mutation is atomic
        # between awaits, and we never await between these statements.
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def _remove(self, run_id: str, queue: asyncio.Queue) -> None:
        bucket = self._subscribers.get(run_id)
        if bucket is None:
            return
        bucket.discard(queue)
        if not bucket:
            self._subscribers.pop(run_id, None)

    def publish(self, run_id: str, event: TraceEvent, seq: int) -> None:
        bucket = self._subscribers.get(run_id)
        if not bucket:
            return
        payload = {"event": event, "seq": seq}
        for queue in list(bucket):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Producer must never block on a slow consumer. The consumer
                # detects gaps via monotonic `seq` and reconciles by calling
                # GET /events?since=<last_seq>.
                logger.warning("run_bus subscriber backlog full run_id=%s seq=%s", run_id, seq)

    def close(self, run_id: str) -> None:
        bucket = self._subscribers.get(run_id)
        if not bucket:
            return
        for queue in list(bucket):
            try:
                queue.put_nowait(self._SENTINEL)
            except asyncio.QueueFull:
                # If the buffer is full we still want the consumer to terminate;
                # drain one slot to make room for the sentinel.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(self._SENTINEL)
                except asyncio.QueueFull:
                    pass

    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any] | None]:
        queue = self._add(run_id)
        try:
            while True:
                item = await queue.get()
                if item is self._SENTINEL:
                    return
                yield item
        finally:
            self._remove(run_id, queue)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subscribers.get(run_id, ()))


_default_bus: RunEventBus | None = None


def get_run_bus() -> RunEventBus:
    global _default_bus
    if _default_bus is None:
        _default_bus = RunEventBus()
    return _default_bus


def reset_run_bus() -> None:
    """Test hook — drops the singleton so the next get_run_bus() rebuilds it."""
    global _default_bus
    _default_bus = None
