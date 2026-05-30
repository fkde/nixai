from __future__ import annotations

import asyncio
import json

from app.config import Settings, config_path, load_settings
from app.llm.ollama import OllamaClient
from app.workflow_scratch import InMemoryWorkflowScratchpad
from app.workflows.events import WorkflowEventSink
from app.workflows.executor import WorkflowGraphExecutor
from app.workflows.models import WorkflowDefinition
from app.workflows.nodes import VisionNodeHandler
from app.workflows.phases import WorkflowPhaseDeps
from app.workflows.presets import get_workflow
from app.workflows.resolver import NodeInputResolver
from tests.fakes.ollama import FakeOllamaClient


def test_settings_migration_adds_vision_role() -> None:
    path = config_path()
    path.write_text(
        json.dumps(
            {
                "default_model": "llama3.1:8b",
                "model_roles": [{"role": "assistant", "model": "llama3.1:8b"}],
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings()

    assert any(item.role == "vision" for item in settings.model_roles)
    assert settings.model_for_role("vision") == settings.default_model


def test_ollama_payload_request_preserves_message_images() -> None:
    messages = [{"role": "user", "content": "Analyze", "images": ["aW1hZ2U="]}]

    payload = OllamaClient(Settings()).chat_payload_request(messages, model="llava", stream=False)

    assert payload["messages"][0]["images"] == ["aW1hZ2U="]
    assert payload["model"] == "llava"
    assert payload["stream"] is False


def test_vision_node_handler_fails_without_image_input() -> None:
    workflow = WorkflowDefinition.model_validate(
        {"id": "vision_missing", "name": "Vision Missing", "nodes": [{"id": "vision", "type": "vision"}]}
    )
    node = workflow.node("vision")
    assert node is not None

    result = asyncio.run(
        VisionNodeHandler().run(workflow, node, state(), deps(), NodeInputResolver())
    )

    assert result.status == "failed"
    assert "needs at least one" in (result.error or "")


def test_vision_node_writes_configured_output_field() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "vision_output",
            "name": "Vision Output",
            "nodes": [
                {
                    "id": "vision",
                    "type": "vision",
                    "role": "vision",
                    "input": ["attachments"],
                    "output": "ocr_text",
                    "prompt": "Extract text.",
                },
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "vision", "to": "answer"}],
        }
    )
    initial = state()
    initial["attachments"] = [attachment()]

    result = asyncio.run(
        WorkflowGraphExecutor(handlers={"answer": StaticAnswerHandler()}).run(
            workflow,
            initial,
            deps(response_text="Extracted text"),
            WorkflowEventSink(),
        )
    )

    assert result.status == "done"
    assert result.state["ocr_text"] == "Extracted text"
    assert result.answer == "Done."


def test_bundled_vision_workflow_validates() -> None:
    workflow = get_workflow("vision_extract", "chat")

    assert workflow is not None
    assert workflow.node("vision") is not None
    assert workflow.node("vision").type == "vision"


def state() -> dict[str, object]:
    return {
        "chat_id": "chat-1",
        "mode": "chat",
        "user_message": "Please read this image",
        "workflow_run_id": "run-1",
        "workflow_scratch_path": "memory",
        "workflow_rounds": [],
        "effort": "medium",
        "effort_context": "effort",
        "workspace": "",
        "runtime_context": "runtime",
        "memory": "memory",
        "code_context": "",
        "agentic_context": "",
        "history": [],
        "attachments": [],
    }


def attachment() -> dict[str, object]:
    return {
        "name": "doc.png",
        "mime_type": "image/png",
        "size": 5,
        "data": "aW1hZ2U=",
    }


def deps(response_text: str = "Vision response") -> WorkflowPhaseDeps:
    return WorkflowPhaseDeps(
        settings=Settings(effort="medium"),
        ollama=FakeOllamaClient(response_text=response_text),
        event_sink=WorkflowEventSink(),
        scratchpad=InMemoryWorkflowScratchpad(),
    )


class StaticAnswerHandler:
    async def run(self, workflow, node, state, deps, resolver):
        from app.workflows.nodes import NodeResult

        return NodeResult(node_id=node.id, status="done", output="Done.", summary="Answer ready.")
