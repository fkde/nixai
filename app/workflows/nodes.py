from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.json_utils import parse_json_object
from app.llm.ollama import OllamaError
from app.roles import role_prompt
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
logger = logging.getLogger(__name__)


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
        tool_instruction = str(node.prompt or "").strip()
        prompt = tool_instruction or str(state.get("user_message") or "")
        deps.event_sink.emit(node.id, "status", "Tool agent is planning approved tool use.")
        result = await AgenticRunner(deps.ollama).run_inline(
            title=node.title or node.id,
            prompt=prompt,
            reason=f"workflow:{node.id}",
            context=inputs,
            trace=deps.trace,
            node_id=node.id,
        )
        status = "done" if result.get("status") == "success" else "needs_user"
        summary = str(result.get("summary") or "Tool agent completed.")
        deps.event_sink.emit(node.id, status, summary)
        return NodeResult(
            node_id=node.id, status=status, output=result, summary=summary, error=result.get("error") or None
        )


class VisionNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        del workflow
        input_keys = node.input or ["attachments"]
        inputs = {key: resolver.resolve_key(str(key), state) for key in input_keys}
        images = self._collect_images(inputs)
        if not images:
            message = "Vision node needs at least one PNG, JPEG, or WebP image attachment as input."
            deps.event_sink.emit(node.id, "failed", message)
            return NodeResult(node_id=node.id, status="failed", summary=message, error=message)

        deps.event_sink.emit(node.id, "status", "Vision model is analyzing image input.")
        role = node.role or "vision"
        system_prompt = self._system_prompt(role, state, node)
        user_payload = {
            "user_message": state.get("user_message"),
            "workflow_context": {
                "mode": state.get("mode"),
                "effort": state.get("effort"),
                "loop_context": state.get("loop_context"),
                "subworkflow_context": state.get("subworkflow_context"),
            },
            "inputs": self._metadata_only(inputs),
            "instruction": node.prompt,
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False), "images": images},
        ]
        model = deps.settings.model_for_role(role)
        started_at = asyncio.get_event_loop().time()
        try:
            response = await deps.ollama.chat_payload(
                messages, model=model, response_format="json" if node.expects_json else None
            )
        except OllamaError as exc:
            message = (
                "Vision model call failed. Check that the selected Ollama model supports image input "
                f"and is available. Detail: {exc}"
            )
            deps.event_sink.emit(node.id, "failed", message)
            return NodeResult(node_id=node.id, status="failed", summary=message, error=message)
        except Exception as exc:
            logger.warning("vision node model call failed node_id=%s model=%s", node.id, model, exc_info=True)
            message = (
                "Vision model call failed. Check that the selected Ollama model supports image input "
                f"and is available. Detail: {exc}"
            )
            deps.event_sink.emit(node.id, "failed", message)
            return NodeResult(node_id=node.id, status="failed", summary=message, error=message)

        output: Any = response
        if node.expects_json:
            try:
                output = json.loads(response)
            except ValueError:
                fallback = parse_json_object(response, fallback={})
                if not fallback:
                    message = "Vision node expected valid JSON, but the model returned non-JSON output."
                    deps.event_sink.emit(node.id, "failed", message)
                    return NodeResult(node_id=node.id, status="failed", summary=message, error=message)
                output = fallback
        if deps.trace is not None:
            deps.trace.emit_llm_call(
                node_id=node.id,
                model=model or "",
                prompt=self._metadata_only(messages),
                response=response,
                duration_ms=int((asyncio.get_event_loop().time() - started_at) * 1000),
            )
        deps.event_sink.emit(node.id, "done", "Vision analysis complete.")
        return NodeResult(node_id=node.id, status="done", output=output, summary="Vision analysis complete.")

    def _system_prompt(self, role: str, state: WorkflowState, node: WorkflowNode) -> str:
        instruction = str(node.prompt or "").strip()
        json_instruction = ""
        if node.expects_json:
            json_instruction = (
                "\n\nReturn strict valid JSON only. Do not wrap it in Markdown code fences and do not add prose."
            )
        node_instruction = f"\n\n## Vision Instruction\n{instruction}" if instruction else ""
        return (
            f"{role_prompt(role or 'VISION')}\n\n"
            f"{state.get('runtime_context') or ''}\n\n"
            f"{state.get('effort_context') or ''}\n\n"
            "Analyze only the supplied image inputs. Use the workflow context as supporting context, "
            "but do not invent text or visual details that are not visible."
            f"{node_instruction}"
            f"{json_instruction}"
        ).strip()

    def _collect_images(self, value: Any) -> list[str]:
        images: list[str] = []

        def visit(item: Any) -> None:
            if len(images) >= 4:
                return
            if isinstance(item, dict):
                data = item.get("data")
                mime_type = str(item.get("mime_type") or "").lower()
                if isinstance(data, str) and data.strip() and mime_type in {"image/png", "image/jpeg", "image/webp"}:
                    images.append(data.strip())
                    return
                for child in item.values():
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)
        return images

    def _metadata_only(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: ("[base64 image data omitted]" if key == "data" else self._metadata_only(child))
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [self._metadata_only(item) for item in value]
        return value


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
        "report": ReviewerNodeHandler(),
        "judge": JudgeNodeHandler(),
        "decision": JudgeNodeHandler(),
        "answer": answer,
        "end": answer,
        "needs_user": answer,
        "pause": PauseNodeHandler(),
        "tool_agent": ToolAgentNodeHandler(),
        "vision": VisionNodeHandler(),
    }
