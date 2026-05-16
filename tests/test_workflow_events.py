from __future__ import annotations

from app.workflows.events import StreamStatsBuilder, WorkflowEventSink


def test_workflow_event_sink_records_and_callbacks() -> None:
    callbacks = []
    sink = WorkflowEventSink(callback=callbacks.append)

    recorded = sink.emit("node", "status", "Working")
    transient = sink.emit("answer", "token", "chunk", record=False)

    assert sink.events == [recorded]
    assert callbacks == [recorded, transient]
    assert sink.has_callback is True


def test_stream_stats_builder_adds_tokens_per_second() -> None:
    stats = StreamStatsBuilder.from_event(
        {
            "eval_count": 40,
            "eval_duration": 2_000_000_000,
            "prompt_eval_count": 5,
            "prompt_eval_duration": 1_000_000,
        }
    )

    assert stats["tokens_per_second"] == 20.0
    assert stats["prompt_eval_count"] == 5
