from __future__ import annotations

import asyncio

from app.workflows.run_bus import RunEventBus
from app.workflows.runtime_trace import TraceEvent


def _event(run_id: str = "r", node: str = "n", type_: str = "node_started") -> TraceEvent:
    return TraceEvent(run_id=run_id, workflow_id="wf", node_id=node, type=type_)


def _run(coro):
    return asyncio.run(coro)


def test_subscriber_receives_published_events_in_order() -> None:
    async def scenario() -> list[tuple[int, str]]:
        bus = RunEventBus()
        received: list[tuple[int, str]] = []

        async def consume() -> None:
            async for item in bus.subscribe("r"):
                received.append((item["seq"], item["event"].node_id))
                if len(received) == 3:
                    return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        for seq, node in [(1, "a"), (2, "b"), (3, "c")]:
            bus.publish("r", _event(node=node), seq)
        await asyncio.wait_for(task, timeout=1.0)
        return received

    assert _run(scenario()) == [(1, "a"), (2, "b"), (3, "c")]


def test_close_terminates_subscriber() -> None:
    async def scenario() -> tuple[list[int], int]:
        bus = RunEventBus()
        received: list[int] = []

        async def consume() -> None:
            async for item in bus.subscribe("r"):
                received.append(item["seq"])

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        bus.publish("r", _event(), 1)
        await asyncio.sleep(0)
        bus.close("r")
        await asyncio.wait_for(task, timeout=1.0)
        return received, bus.subscriber_count("r")

    received, remaining = _run(scenario())
    assert received == [1]
    assert remaining == 0


def test_publish_to_unsubscribed_run_is_noop() -> None:
    bus = RunEventBus()
    bus.publish("ghost", _event(), 1)  # must not raise
    assert bus.subscriber_count("ghost") == 0


def test_full_queue_drops_silently_and_does_not_block_producer() -> None:
    async def scenario() -> list[int]:
        bus = RunEventBus(queue_size=2)
        # Subscribe but don't consume yet so the queue saturates.
        gen = bus.subscribe("r").__aiter__()
        register = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0)
        # Publish 4 events with queue_size=2 — must not block, third+fourth drop.
        bus.publish("r", _event(node="a"), 1)
        bus.publish("r", _event(node="b"), 2)
        bus.publish("r", _event(node="c"), 3)
        bus.publish("r", _event(node="d"), 4)
        first = await asyncio.wait_for(register, timeout=1.0)
        second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        bus.close("r")
        # Consumer drains the remaining items + sentinel; should not hang.
        seqs = [first["seq"], second["seq"]]
        try:
            while True:
                seqs.append((await asyncio.wait_for(gen.__anext__(), timeout=1.0))["seq"])
        except StopAsyncIteration:
            pass
        return seqs

    seqs = _run(scenario())
    # We received only what fit in the queue (the first two); the rest were dropped.
    assert seqs == [1, 2]


def test_multiple_subscribers_each_get_events_independently() -> None:
    async def scenario() -> tuple[list[int], list[int]]:
        bus = RunEventBus()
        a_received: list[int] = []
        b_received: list[int] = []

        async def consume(target: list[int]) -> None:
            async for item in bus.subscribe("r"):
                target.append(item["seq"])
                if len(target) == 2:
                    return

        tasks = [asyncio.create_task(consume(a_received)), asyncio.create_task(consume(b_received))]
        await asyncio.sleep(0)
        bus.publish("r", _event(), 1)
        bus.publish("r", _event(), 2)
        await asyncio.gather(*(asyncio.wait_for(task, timeout=1.0) for task in tasks))
        return a_received, b_received

    a, b = _run(scenario())
    assert a == [1, 2]
    assert b == [1, 2]
