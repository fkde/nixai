from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.workflows.models import WorkflowDefinition, WorkflowNode
from app.workflows.phases import (
    WorkflowPhaseDeps,
    build_plan,
    final_answer,
    judge,
    replan_for_retry,
    review,
    run_workers,
)
from app.workflows.resolver import NodeInputResolver
from app.workflows.state import WorkflowState


NodeStatus = Literal["done", "retry", "needs_user", "failed", "skipped"]


@dataclass
class NodeResult:
    node_id: str
    status: NodeStatus
    output: Any = None
    summary: str = ""
    error: str | None = None

    def as_state_value(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "output": self.output,
            "summary": self.summary,
            "error": self.error,
        }


class NodeHandler(Protocol):
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult: ...


class RoleNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        del resolver
        if state.get("retry_feedback"):
            plan = await replan_for_retry(workflow, state, deps)
        else:
            plan = await build_plan(workflow, state, deps)
        return NodeResult(
            node_id=node.id, status="done", output=plan, summary=str(plan.get("summary") or "Plan ready.")
        )


class WorkerPoolNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        del resolver
        reports = await run_workers(workflow, state, deps)
        return NodeResult(node_id=node.id, status="done", output=reports, summary=f"{len(reports)} worker report(s).")


class ReviewerNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        del resolver
        result = await review(workflow, state, deps)
        status = "done" if str(result.get("status") or "").lower() == "approved" else "retry"
        return NodeResult(
            node_id=node.id,
            status=status,
            output=result,
            summary=str(result.get("summary") or f"Review status: {result.get('status', 'unknown')}."),
        )


class JudgeNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        del resolver
        decision = await judge(workflow, state, deps)
        status = str(decision.get("status") or "done").strip().lower()
        if status not in {"done", "retry", "needs_user"}:
            status = "done"
        return NodeResult(
            node_id=node.id,
            status=status,  # type: ignore[arg-type]
            output=decision,
            summary=str(decision.get("reason") or f"Judge decision: {status}."),
        )


class AnswerNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        del resolver
        answer = await final_answer(workflow, state, deps, node_id=node.id)
        decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
        status = "needs_user" if str(decision.get("status") or "").lower() == "needs_user" else "done"
        return NodeResult(node_id=node.id, status=status, output=answer, summary="Answer ready.")


class ToolAgentNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        del workflow
        from app.agentic_runner import AgenticRunner

        inputs = resolver.resolve(node, state)
        prompt = node.prompt or str(state.get("user_message") or "")
        deps.event_sink.emit(node.id, "status", "Tool agent is planning approved tool use.")
        result = await AgenticRunner(deps.ollama).run_inline(
            title=node.title or node.id, prompt=prompt, reason=f"workflow:{node.id}", context=inputs
        )
        status = "done" if result.get("status") == "success" else "needs_user"
        summary = str(result.get("summary") or "Tool agent completed.")
        deps.event_sink.emit(node.id, status, summary)
        return NodeResult(
            node_id=node.id, status=status, output=result, summary=summary, error=result.get("error") or None
        )


class PauseNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        del workflow
        inputs = resolver.resolve(node, state)
        decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
        feedback = decision.get("feedback") if isinstance(decision.get("feedback"), list) else []
        prompt_parts = [str(decision.get("reason") or "").strip()]
        prompt_parts.extend(f"- {item}" for item in feedback if str(item).strip())
        decision_prompt = "\n".join(part for part in prompt_parts if part).strip()
        prompt = node.prompt or decision_prompt or node.title or "The workflow needs user input before it can continue."
        output = {"status": "paused", "prompt": prompt, "node": node.id, "inputs": inputs}
        state["pause"] = output
        deps.event_sink.emit(node.id, "paused", prompt, {"pause": output})
        return NodeResult(node_id=node.id, status="needs_user", output=output, summary=prompt)


def default_node_handlers() -> dict[str, NodeHandler]:
    role = RoleNodeHandler()
    answer = AnswerNodeHandler()
    return {
        "role": role,
        "orchestrator": role,
        "worker_pool": WorkerPoolNodeHandler(),
        "reviewer": ReviewerNodeHandler(),
        "judge": JudgeNodeHandler(),
        "answer": answer,
        "end": answer,
        "needs_user": answer,
        "pause": PauseNodeHandler(),
        "tool_agent": ToolAgentNodeHandler(),
    }
