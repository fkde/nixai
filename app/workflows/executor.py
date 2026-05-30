from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import sqlite3
import time
from collections import deque
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

from app.workflows.conditions import WorkflowConditionEvaluator
from app.workflows.events import WorkflowEventSink
from app.workflows.models import WorkflowDefinition, WorkflowEdge, WorkflowResult
from app.workflows.nodes import NodeHandler, NodeResult, default_node_handlers
from app.workflows.phases import WorkflowPhaseDeps, markdown_data, note
from app.workflows.prompts import build_node_instruction_block
from app.workflows.resolver import NodeInputResolver
from app.workflows.runtime_trace import TraceEmitter, cap_snapshot
from app.workflows.state import WorkflowState, compact_workflow_state, record_workflow_round


class WorkflowGraphExecutor:
    def __init__(
        self,
        handlers: dict[str, NodeHandler] | None = None,
        condition_evaluator: WorkflowConditionEvaluator | None = None,
        resolver: NodeInputResolver | None = None,
        max_node_steps: int = 32,
    ) -> None:
        self.handlers = {**default_node_handlers(), **(handlers or {})}
        if handlers:
            if "reviewer" in handlers and "report" not in handlers:
                self.handlers["report"] = handlers["reviewer"]
            if "judge" in handlers and "decision" not in handlers:
                self.handlers["decision"] = handlers["judge"]
        self.condition_evaluator = condition_evaluator or WorkflowConditionEvaluator()
        self.resolver = resolver or NodeInputResolver()
        self.max_node_steps = max(1, max_node_steps)

    async def run(
        self,
        workflow: WorkflowDefinition,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        start_node_ids: list[str] | None = None,
        trace: TraceEmitter | None = None,
    ) -> WorkflowResult:
        # Materialise any implicit routing (e.g. io.input → real start nodes)
        # as real edges in a compiled copy so both the executor and any trace
        # consumers see the same edges. Persistence is unaffected — the
        # original workflow object is never mutated.
        workflow = compile_workflow_for_execution(workflow)
        state.setdefault("node_results", {})
        queue = deque(start_node_ids or self._start_node_ids(workflow))
        steps = 0
        final_status = "done"

        if not queue:
            event_sink.emit("workflow", "failed", "Workflow has no executable start node.")
            return self._result(workflow, state, deps, event_sink, final_status="failed", answer="")

        while queue and steps < self.max_node_steps:
            node_id = queue.popleft()
            node = workflow.node(node_id)
            if node is None:
                result = NodeResult(node_id=node_id, status="failed", error=f"Unknown node: {node_id}")
                self._store_result(state, result)
                event_sink.emit(node_id, "failed", result.error or "Unknown node.")
                if trace is not None:
                    trace.emit("node_failed", node_id=node_id, payload={"error": result.error or "Unknown node."})
                final_status = "failed"
                continue

            result = await self._run_node(workflow, node.id, state, deps, event_sink, trace)
            steps += 1
            final_status = result.status if result.status in {"failed", "needs_user"} else final_status
            self._apply_compatible_state(node.output, result, state, deps, workflow, event_sink)

            if node.type in {"answer", "end", "needs_user"}:
                final_status = result.status
                break
            if node.type == "io" and node.id == "output":
                final_status = result.status
                break
            if node.type == "pause" or result.status == "needs_user":
                final_status = "needs_user"
                break
            # Check pause once before deciding the next branch — applies
            # equally to success and failure paths so a pause requested while
            # a node was running is always honoured at the next safe point.
            if self._consume_pause_signal(state):
                state["pause"] = {"node": node.id, "kind": "cooperative"}
                state["current_node"] = node.id
                event_sink.emit(node.id, "pause", "Workflow paused after the current step.")
                final_status = "paused"
                break

            if result.status == "failed":
                next_nodes = self.failure_node_ids(workflow, node.id)
                self._emit_edge_events(workflow, node.id, next_nodes, "error", trace)
                if not next_nodes:
                    break
                queue.extend(next_nodes)
                continue

            next_nodes = self.next_node_ids(workflow, node.id, state)
            self._emit_edge_events(workflow, node.id, next_nodes, "", trace)
            if next_nodes:
                queue.extend(next_nodes)

        if steps >= self.max_node_steps and queue:
            final_status = "failed"
            event_sink.emit("workflow", "failed", f"Workflow stopped after {self.max_node_steps} node step(s).")

        answer = str(state.get("final_answer") or "")
        return self._result(workflow, state, deps, event_sink, final_status=final_status, answer=answer)

    async def _run_node(
        self,
        workflow: WorkflowDefinition,
        node_id: str,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        trace: TraceEmitter | None = None,
    ) -> NodeResult:
        node = workflow.node(node_id)
        if node is None:
            return NodeResult(node_id=node_id, status="failed", error=f"Unknown node: {node_id}")

        started_step_id: str | None = None
        started_at = time.perf_counter()
        if trace is not None:
            input_snapshot, truncated = cap_snapshot(self._input_snapshot(node, state))
            prompt_snapshot, prompt_truncated = cap_snapshot(node.prompt or None)
            instruction_block, instruction_block_truncated = cap_snapshot(
                build_node_instruction_block(node) or None
            )
            started_step_id = trace.emit(
                "node_started",
                node_id=node.id,
                payload={
                    "node_type": node.type,
                    "input_snapshot": input_snapshot,
                    "input_snapshot_truncated": truncated,
                    "prompt": prompt_snapshot,
                    "prompt_snapshot": prompt_snapshot,
                    "prompt_snapshot_truncated": prompt_truncated,
                    "node_instruction": prompt_snapshot,
                    "node_instruction_block": instruction_block,
                    "node_instruction_block_truncated": instruction_block_truncated,
                    "execution_profile": node.execution_profile or workflow.execution_profile or "",
                },
            )

        with self._maybe_scope(trace, started_step_id):
            result = await self._dispatch_node(workflow, node_id, state, deps, event_sink, trace)

        if trace is not None:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            output_snapshot, truncated = cap_snapshot(result.output)
            if result.status == "failed":
                trace.emit(
                    "node_failed",
                    node_id=node.id,
                    payload={
                        "error": result.error or result.summary,
                        "duration_ms": duration_ms,
                    },
                )
            else:
                trace.emit(
                    "node_finished",
                    node_id=node.id,
                    payload={
                        "status": result.status,
                        "output_snapshot": output_snapshot,
                        "output_snapshot_truncated": truncated,
                        "summary": result.summary,
                        "duration_ms": duration_ms,
                    },
                )
        return result

    async def _dispatch_node(
        self,
        workflow: WorkflowDefinition,
        node_id: str,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        trace: TraceEmitter | None,
    ) -> NodeResult:
        node = workflow.node(node_id)
        if node is None:
            return NodeResult(node_id=node_id, status="failed", error=f"Unknown node: {node_id}")
        if node.type == "for_each":
            result = await self._run_for_each(workflow, node_id, state, deps, event_sink, trace)
            self._store_result(state, result)
            return result
        if node.type == "while":
            result = await self._run_while(workflow, node_id, state, deps, event_sink, trace)
            self._store_result(state, result)
            return result
        if node.type == "workflow":
            result = await self._run_subworkflow(workflow, node_id, state, deps, event_sink, trace)
            self._store_result(state, result)
            return result
        if node.type == "io":
            if node.id == "input":
                output: Any = state.get("user_message", "")
            else:
                output = ""
                for key in node.input or []:
                    cleaned = str(key).strip()
                    if not cleaned:
                        continue
                    if cleaned in state and state[cleaned] not in (None, ""):
                        output = state[cleaned]
                        break
                    resolved = self.resolver.resolve_key(cleaned, state)
                    if resolved not in (None, ""):
                        output = resolved
                        break
                if not output:
                    output = state.get("final_answer") or state.get("answer") or ""
                state["final_answer"] = output
            result = NodeResult(node_id=node.id, status="done", output=output, summary="")
            self._store_result(state, result)
            return result
        handler = self.handlers.get(node.type)
        if handler is None:
            result = NodeResult(
                node_id=node.id,
                status="failed",
                summary=f"Unsupported workflow node type: {node.type}",
                error=f"Unsupported workflow node type: {node.type}",
            )
            self._store_result(state, result)
            event_sink.emit(node.id, "failed", result.summary)
            return result
        result = await self._run_handler_with_retry(workflow, node_id, state, deps, event_sink, handler)
        self._store_result(state, result)
        return result

    def _input_snapshot(self, node: Any, state: WorkflowState) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        try:
            for key in node.input or []:
                cleaned = str(key).strip()
                if not cleaned:
                    continue
                if cleaned in state:
                    snapshot[cleaned] = self._snapshot_safe_value(state[cleaned])
                else:
                    resolved = self.resolver.resolve_key(cleaned, state)
                    if resolved is not None:
                        snapshot[cleaned] = self._snapshot_safe_value(resolved)
        except Exception:
            return snapshot
        return snapshot

    def _snapshot_safe_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: ("[base64 image data omitted]" if key == "data" else self._snapshot_safe_value(child))
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [self._snapshot_safe_value(item) for item in value]
        return value

    @contextlib.contextmanager
    def _maybe_scope(self, trace: TraceEmitter | None, parent_step_id: str | None) -> Iterator[None]:
        if trace is not None and parent_step_id is not None:
            with trace.scope(parent_step_id):
                yield
        else:
            yield

    def _emit_edge_events(
        self,
        workflow: WorkflowDefinition,
        from_node: str,
        to_nodes: list[str],
        when_filter: str,
        trace: TraceEmitter | None,
    ) -> None:
        if trace is None or not to_nodes:
            return
        for edge in workflow.edges:
            if edge.from_node != from_node or edge.to not in to_nodes:
                continue
            edge_when = str(edge.when or "").strip()
            if when_filter == "error" and edge_when.lower() != "error":
                continue
            if when_filter == "" and edge_when.lower() == "error":
                continue
            trace.emit(
                "edge_traversed",
                node_id=from_node,
                payload={"from": edge.from_node, "to": edge.to, "when": edge.when},
            )

    async def _run_handler_with_retry(
        self,
        workflow: WorkflowDefinition,
        node_id: str,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        handler: NodeHandler,
    ) -> NodeResult:
        node = workflow.node(node_id)
        if node is None:
            return NodeResult(node_id=node_id, status="failed", error=f"Unknown node: {node_id}")
        max_retries = max(0, node.retry.max)
        attempts = max_retries + 1
        last_result: NodeResult | None = None
        for attempt in range(1, attempts + 1):
            if attempt > 1:
                event_sink.emit(node.id, "retry", f"Retrying node ({attempt}/{attempts}).")
                if node.retry.backoff > 0:
                    await asyncio.sleep(node.retry.backoff)
            try:
                result = await handler.run(workflow, node, state, deps, self.resolver)
            except Exception as exc:
                result = NodeResult(node_id=node.id, status="failed", summary="Node failed.", error=str(exc))
                event_sink.emit(node.id, "failed", f"Node failed: {exc}")
            last_result = result
            if result.status != "failed":
                return result
        return last_result or NodeResult(node_id=node.id, status="failed", summary="Node failed.")

    async def _run_for_each(
        self,
        workflow: WorkflowDefinition,
        node_id: str,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        trace: TraceEmitter | None = None,
    ) -> NodeResult:
        node = workflow.node(node_id)
        if node is None:
            return NodeResult(node_id=node_id, status="failed", error=f"Unknown node: {node_id}")
        items_key = str(node.config.get("items") or (node.input[0] if node.input else "")).strip()
        body = self._configured_body_nodes(node.config.get("body"))
        if not items_key:
            return NodeResult(node_id=node.id, status="failed", summary="for_each node is missing an items input.")
        if not body:
            return NodeResult(node_id=node.id, status="failed", summary="for_each node is missing body nodes.")
        items = self.resolver.resolve_key(items_key, state)
        if not isinstance(items, list):
            return NodeResult(node_id=node.id, status="failed", summary=f"for_each input is not a list: {items_key}")

        previous_item = state.get("item")
        previous_index = state.get("item_index")
        previous_loop_context = state.get("loop_context")
        outputs: list[Any] = []
        event_sink.emit(node.id, "status", f"Iterating over {len(items)} item(s).")
        try:
            if node.prompt.strip():
                state["loop_context"] = {"node_id": node.id, "instruction": node.prompt.strip()}
            for index, item in enumerate(items):
                state["item"] = item
                state["item_index"] = index
                item_outputs: dict[str, Any] = {}
                event_sink.emit(node.id, "status", f"Iteration item {index + 1}/{len(items)}.")
                for body_node_id in body:
                    result = await self._run_node(workflow, body_node_id, state, deps, event_sink, trace)
                    body_node = workflow.node(body_node_id)
                    self._apply_compatible_state(
                        body_node.output if body_node else "", result, state, deps, workflow, event_sink
                    )
                    item_outputs[body_node_id] = result.output
                    if result.status in {"failed", "needs_user"}:
                        return NodeResult(
                            node_id=node.id,
                            status=result.status,
                            output=outputs,
                            summary=result.summary,
                            error=result.error,
                        )
                outputs.append(item_outputs[body[0]] if len(body) == 1 else item_outputs)
        finally:
            self._restore_loop_value(state, "item", previous_item)
            self._restore_loop_value(state, "item_index", previous_index)
            self._restore_loop_value(state, "loop_context", previous_loop_context)
        event_sink.emit(node.id, "done", f"Completed {len(outputs)} item iteration(s).")
        return NodeResult(node_id=node.id, status="done", output=outputs, summary=f"{len(outputs)} item(s) processed.")

    async def _run_while(
        self,
        workflow: WorkflowDefinition,
        node_id: str,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        trace: TraceEmitter | None = None,
    ) -> NodeResult:
        node = workflow.node(node_id)
        if node is None:
            return NodeResult(node_id=node_id, status="failed", error=f"Unknown node: {node_id}")
        body = self._configured_body_nodes(node.config.get("body"))
        break_when = node.break_when or str(node.config.get("break_when") or "").strip()
        max_iterations = self._config_int(
            node.config.get("max_iterations"), default=workflow.max_iterations, min_value=1
        )
        if not body:
            return NodeResult(node_id=node.id, status="failed", summary="while node is missing body nodes.")
        if not break_when:
            return NodeResult(node_id=node.id, status="failed", summary="while node is missing break_when.")

        outputs: list[Any] = []
        previous_loop_context = state.get("loop_context")
        if node.prompt.strip():
            state["loop_context"] = {
                "node_id": node.id,
                "instruction": node.prompt.strip(),
                "goal": "Repeat body nodes until the break condition is met.",
            }
        try:
            for index in range(max_iterations):
                if self.condition_evaluator.matches(break_when, state):
                    event_sink.emit(node.id, "done", f"Loop stopped before iteration {index + 1}.")
                    return NodeResult(
                        node_id=node.id, status="done", output=outputs, summary="Loop break condition matched."
                    )
                state["loop_iteration"] = index + 1
                event_sink.emit(node.id, "status", f"Loop iteration {index + 1}/{max_iterations}.")
                iteration_outputs: dict[str, Any] = {}
                for body_node_id in body:
                    result = await self._run_node(workflow, body_node_id, state, deps, event_sink, trace)
                    body_node = workflow.node(body_node_id)
                    self._apply_compatible_state(
                        body_node.output if body_node else "", result, state, deps, workflow, event_sink
                    )
                    iteration_outputs[body_node_id] = result.output
                    if result.status in {"failed", "needs_user"}:
                        return NodeResult(
                            node_id=node.id,
                            status=result.status,
                            output=outputs,
                            summary=result.summary,
                            error=result.error,
                        )
                outputs.append(iteration_outputs[body[0]] if len(body) == 1 else iteration_outputs)
        finally:
            self._restore_loop_value(state, "loop_context", previous_loop_context)
        event_sink.emit(node.id, "done", f"Loop reached {max_iterations} iteration limit.")
        return NodeResult(node_id=node.id, status="done", output=outputs, summary="Loop iteration limit reached.")

    async def _run_subworkflow(
        self,
        workflow: WorkflowDefinition,
        node_id: str,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        trace: TraceEmitter | None = None,
    ) -> NodeResult:
        from app.workflows.presets import get_workflow

        node = workflow.node(node_id)
        if node is None:
            return NodeResult(node_id=node_id, status="failed", error=f"Unknown node: {node_id}")
        ref = node.ref or str(node.config.get("ref") or "").strip()
        if not ref:
            return NodeResult(node_id=node.id, status="failed", summary="workflow node is missing ref.")
        stack = [str(item) for item in state.get("workflow_stack", []) if str(item).strip()]
        if ref in stack or ref == workflow.id:
            return NodeResult(node_id=node.id, status="failed", summary=f"Recursive workflow ref blocked: {ref}")
        child = get_workflow(ref, state.get("mode"))
        if child is None:
            return NodeResult(node_id=node.id, status="failed", summary=f"Unknown workflow ref: {ref}")
        child_state = copy.deepcopy(state)
        child_state["workflow_stack"] = [*stack, workflow.id]
        if node.prompt.strip():
            child_state["subworkflow_context"] = {
                "node_id": node.id,
                "instruction": node.prompt.strip(),
            }
        event_sink.emit(node.id, "status", f"Running sub-workflow: {child.name}.")
        result = await WorkflowGraphExecutor(
            handlers=self.handlers,
            condition_evaluator=self.condition_evaluator,
            resolver=self.resolver,
            max_node_steps=self.max_node_steps,
        ).run(child, child_state, deps, event_sink, trace=trace)
        child_node_results = (
            child_state.get("node_results") if isinstance(child_state.get("node_results"), dict) else {}
        )
        parent_node_results = state.get("node_results") if isinstance(state.get("node_results"), dict) else {}
        parent_node_results.update(child_node_results)
        state["node_results"] = parent_node_results
        state.update(
            {key: value for key, value in child_state.items() if key not in {"workflow_stack", "node_results"}}
        )
        status = "done" if result.status == "done" else result.status
        return NodeResult(node_id=node.id, status=status, output=result.state, summary=result.answer)

    def _start_node_ids(self, workflow: WorkflowDefinition) -> list[str]:
        preferred = [
            node.id for node in workflow.nodes if node.type in {"input", "start"} or node.id in {"input", "start"}
        ]
        if preferred:
            return preferred
        incoming = {edge.to for edge in workflow.edges}
        body_nodes = self._body_node_ids(workflow)
        starts = [node.id for node in workflow.nodes if node.id not in incoming and node.id not in body_nodes]
        return starts or ([workflow.nodes[0].id] if workflow.nodes else [])

    def next_node_ids(self, workflow: WorkflowDefinition, node_id: str, state: WorkflowState) -> list[str]:
        return [
            edge.to
            for edge in workflow.edges
            if edge.from_node == node_id
            and str(edge.when or "").strip().lower() != "error"
            and self.condition_evaluator.matches(edge.when, state)
        ]

    def failure_node_ids(self, workflow: WorkflowDefinition, node_id: str) -> list[str]:
        return [
            edge.to
            for edge in workflow.edges
            if edge.from_node == node_id and str(edge.when or "").strip().lower() == "error"
        ]

    def _store_result(self, state: WorkflowState, result: NodeResult) -> None:
        node_results = state.get("node_results")
        if not isinstance(node_results, dict):
            node_results = {}
            state["node_results"] = node_results
        node_results[result.node_id] = result.as_state_value()

    def _apply_compatible_state(
        self,
        output_name: str,
        result: NodeResult,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        workflow: WorkflowDefinition,
        event_sink: WorkflowEventSink,
    ) -> None:
        key = output_name or self._default_output_name(workflow, result.node_id)
        if key:
            state[key] = result.output
        if key == "worker_reports":
            note(deps, state, f"Iteration {state.get('iteration') or 1} worker reports", markdown_data(result.output))
        if key == "review":
            note(deps, state, f"Iteration {state.get('iteration') or 1} review", markdown_data(result.output))
        if key == "decision" and isinstance(result.output, dict):
            self._after_decision(state, deps, workflow, event_sink)
        if key == "final_answer":
            state["final_answer"] = result.output
            note(deps, state, "Final answer", str(result.output or ""))

    def _after_decision(
        self, state: WorkflowState, deps: WorkflowPhaseDeps, workflow: WorkflowDefinition, event_sink: WorkflowEventSink
    ) -> None:
        reports = state.get("worker_reports") if isinstance(state.get("worker_reports"), list) else []
        review = state.get("review") if isinstance(state.get("review"), dict) else {}
        decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
        iteration = int(state.get("iteration") or 1)
        state["iteration"] = iteration
        note(deps, state, f"Iteration {iteration} decision", markdown_data(decision))
        record_workflow_round(state, reports, review, decision)

        status = str(decision.get("status") or "done").strip().lower()
        if status != "retry":
            return
        if iteration >= workflow.max_iterations:
            decision["status"] = "done"
            decision["reason"] = (
                "Retry limit reached. Synthesize the best user-facing answer from all available evidence, "
                "including caveats and missing verification."
            )
            state["decision"] = decision
            event_sink.emit(
                "decision", "done", "Retry limit reached; synthesizing final answer from available evidence."
            )
            note(deps, state, "Retry limit reached", markdown_data(decision))
            return
        state["iteration"] = iteration + 1
        state["retry_feedback"] = decision.get("feedback") or decision.get("reason") or "Retry requested."
        event_sink.emit(
            "decision", "retry", f"Decision requested another worker pass ({iteration + 1}/{workflow.max_iterations})."
        )

    def _default_output_name(self, workflow: WorkflowDefinition, node_id: str) -> str:
        node = workflow.node(node_id)
        if node is None:
            return ""
        mapping = {
            "role": "plan",
            "orchestrator": "plan",
            "worker_pool": "worker_reports",
            "reviewer": "review",
            "report": "review",
            "judge": "decision",
            "decision": "decision",
            "answer": "final_answer",
            "end": "final_answer",
            "needs_user": "final_answer",
            "pause": "pause",
            "for_each": node.output if (node := workflow.node(node_id)) else "",
            "while": node.output if (node := workflow.node(node_id)) else "",
            "workflow": node.output if (node := workflow.node(node_id)) else "",
            "tool_agent": node.output if (node := workflow.node(node_id)) else "",
            "vision": node.output if (node := workflow.node(node_id)) else "",
        }
        return mapping.get(node.type, "")

    def _configured_body_nodes(self, raw: Any) -> list[str]:
        if isinstance(raw, str):
            raw_items = [raw]
        elif isinstance(raw, list):
            raw_items = raw
        else:
            raw_items = []
        result: list[str] = []
        for item in raw_items:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    def _body_node_ids(self, workflow: WorkflowDefinition) -> set[str]:
        body_nodes: set[str] = set()
        for node in workflow.nodes:
            body_nodes.update(self._configured_body_nodes(node.config.get("body")))
        return body_nodes

    def _restore_loop_value(self, state: WorkflowState, key: str, previous: Any) -> None:
        if previous is None:
            state.pop(key, None)
        else:
            state[key] = previous

    def _consume_pause_signal(self, state: WorkflowState) -> bool:
        run_id = str(state.get("workflow_run_id") or "").strip()
        if not run_id:
            return False
        try:
            from app import database
        except ImportError:
            logger.warning("pause signal lookup skipped — database module unavailable")
            return False
        try:
            if not database.has_workflow_run_signal(run_id, "pause"):
                return False
        except sqlite3.Error:
            # Don't silently pretend the pause didn't happen — surface it so
            # operators see the problem in logs. Returning False here means
            # the workflow continues; that's intentional because we can't
            # confirm the signal, but the warning makes the gap visible.
            logger.warning("pause signal check failed run_id=%s", run_id, exc_info=True)
            return False
        try:
            database.clear_workflow_run_signal(run_id, "pause")
        except sqlite3.Error:
            # Already detected the signal; honour the pause even if clearing
            # fails. The orphan signal will be cleaned up next time.
            logger.warning("pause signal clear failed run_id=%s", run_id, exc_info=True)
        return True

    def _config_int(self, value: Any, *, default: int, min_value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(min_value, parsed)

    def _result(
        self,
        workflow: WorkflowDefinition,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        final_status: str,
        answer: str,
    ) -> WorkflowResult:
        if not answer and state.get("final_answer"):
            answer = str(state.get("final_answer") or "")
        if not answer and final_status == "failed":
            failures = [
                result
                for result in (state.get("node_results") or {}).values()
                if isinstance(result, dict) and result.get("status") == "failed"
            ]
            answer = (
                str((failures[-1] or {}).get("summary") or (failures[-1] or {}).get("error") or "") if failures else ""
            )
        return WorkflowResult(
            workflow_id=workflow.id,
            answer=answer,
            status=final_status,
            events=event_sink.events,
            state=compact_workflow_state(state, scratchpad=deps.scratchpad),
        )


def compile_workflow_for_execution(workflow: WorkflowDefinition) -> WorkflowDefinition:
    """Return a new workflow with implicit routing materialised as real edges.

    The only auto-routing we currently inject is for an `io.input` boundary
    node whose user-authored edges are missing or do not cover the actual
    start nodes. Without this step the executor would dead-end at the input
    node, and the inspector would have no edge to highlight when it ran.

    The input definition is never mutated; persistence is unaffected.
    """
    input_node = next(
        (node for node in workflow.nodes if node.type == "io" and node.id == "input"),
        None,
    )
    if input_node is None:
        return workflow
    explicit_out = [edge for edge in workflow.edges if edge.from_node == input_node.id]
    if explicit_out:
        return workflow

    # Find every "real" start node: not the input, not an io boundary, and not
    # already the target of a non-error/retry edge. Skip pause sources too —
    # they only fire on resume, never as flow entry.
    main_flow_targets: set[str] = set()
    for edge in workflow.edges:
        when = str(edge.when or "").strip().lower()
        if "retry" in when or when == "error":
            continue
        source = workflow.node(edge.from_node)
        if source is not None and source.type == "pause":
            continue
        main_flow_targets.add(edge.to)

    auto_targets = [
        node.id
        for node in workflow.nodes
        if node.id != input_node.id
        and node.type != "io"
        and node.id not in main_flow_targets
    ]
    if not auto_targets:
        return workflow

    extra_edges = [
        WorkflowEdge.model_validate({"from": input_node.id, "to": target_id, "when": ""})
        for target_id in auto_targets
    ]
    return workflow.model_copy(update={"edges": list(workflow.edges) + extra_edges})
