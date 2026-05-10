from __future__ import annotations

import asyncio
import json
import re
from html.parser import HTMLParser
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.effort import effort_context, effort_tool_calls, effort_tool_steps
from app.llm.ollama import OllamaClient, OllamaError
from app.runtime_context import runtime_meta_context
from app.tools.registry import registry


MAX_CONTEXT_CHARS = 34_000
MAX_FETCH_CHARS = 5_500
MAX_TOOL_RESULT_CHARS = 8_000
MAX_TOOL_STEPS = 3
MAX_TOOL_CALLS_PER_STEP = 4
CONTEXT_TOOL_NAMES = {
    "nixai_tools_search",
    "nixai_workspace_list_files",
    "nixai_workspace_read_file",
    "nixai_workspace_search_files",
    "nixai_git_status",
    "nixai_git_diff",
    "nixai_web_search",
    "nixai_web_fetch_url",
    "nixai_web_check_url",
}


class AgenticToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgenticToolPlan(BaseModel):
    action: str = "answer"
    tool_calls: list[AgenticToolCall] = Field(default_factory=list)
    reason: str = ""

    @property
    def wants_tools(self) -> bool:
        return self.action.strip().casefold() in {"use_tools", "tools", "research", "investigate", "web_research"} and bool(
            self.tool_calls
        )


class AgenticContextBuilder:
    def __init__(self, settings: Settings, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = settings
        self.ollama = ollama or OllamaClient(settings, timeout=45.0)

    async def build(self, user_message: str) -> str:
        tool_results: list[dict[str, Any]] = []
        last_reason = ""

        for _ in range(self._max_tool_steps()):
            plan = await self._plan(user_message, tool_results)
            last_reason = plan.reason or last_reason
            if not plan.wants_tools:
                break
            step_results = await self._execute_tool_calls(plan.tool_calls)
            if not step_results:
                break
            tool_results.extend(step_results)

        if not tool_results:
            return ""

        sections = [
            "NixAI agentic tool context:",
            "- The following context was gathered through bounded NixAI tools selected by the Agentic orchestrator.",
            "- Use these tool results as evidence for the answer and cite source URLs when useful.",
            "- If the tool results are thin or unavailable, say so instead of pretending the work is complete.",
            "",
            f"Tool-use reason: {last_reason or 'The orchestrator selected tools for this request.'}",
        ]

        for item in tool_results:
            sections.extend(["", self._format_tool_result(item)])

        context = "\n".join(sections).strip()
        if len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS].rstrip() + "\n...[agentic tool context truncated]"
        return context

    async def _plan(self, user_message: str, tool_results: list[dict[str, Any]]) -> AgenticToolPlan:
        try:
            content = await self.ollama.chat_payload(
                [
                    {"role": "system", "content": self._planning_prompt(user_message)},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "user_request": user_message,
                                "available_tools": self._available_tool_definitions(),
                                "previous_tool_results": self._compact_tool_results(tool_results),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                model=self.settings.model_for_role("orchestrator"),
                response_format="json",
            )
            return AgenticToolPlan.model_validate(self._parse_json(content))
        except (OllamaError, ValidationError, ValueError):
            return AgenticToolPlan(action="answer", reason="Tool planning failed.")

    def _planning_prompt(self, user_message: str) -> str:
        return (
            "You are the Agentic-mode tool planner for NixAI.\n"
            "Decide whether the request needs tool evidence before the assistant answers.\n"
            "You do not answer the user here. You only decide the next tool calls, then stop when enough evidence exists.\n"
            "Return strict JSON only.\n\n"
            f"{runtime_meta_context(user_message)}\n\n"
            "Rules:\n"
            "- Use action=\"use_tools\" when available tools are needed for evidence, current information, public web research, URL content, workspace files, or Git state.\n"
            "- Use action=\"answer\" only when the final answer can be grounded in the conversation and runtime context without tool evidence.\n"
            "- If the final answer would otherwise mention training data, a knowledge cutoff, or missing current access, choose tools instead.\n"
            "- Do not classify reminders or scheduled tasks here; TaskDiscovery handles scheduled tasks before this step.\n"
            "- For public-web work, start with nixai_web_search. After search results are available, use nixai_web_fetch_url for the most relevant public URLs when page content is needed.\n"
            "- For workspace work, search/list first when the exact path is unknown, then read specific files.\n"
            "- Tool arguments must match the tool input schema exactly.\n"
            f"- Request at most {self._max_tool_calls()} tool call(s) per step.\n"
            "- When previous_tool_results already contain enough evidence, return action=\"answer\" with no tool calls.\n\n"
            f"{effort_context(self.settings.effort)}\n\n"
            "JSON schema:\n"
            '{"action":"answer|use_tools","tool_calls":[{"name":"nixai_web_search","arguments":{"query":"...","limit":5}}],"reason":"..."}'
        )

    async def _execute_tool_calls(self, tool_calls: list[AgenticToolCall]) -> list[dict[str, Any]]:
        results = []
        for tool_call in tool_calls[: self._max_tool_calls()]:
            name = tool_call.name.strip()
            arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
            if name not in CONTEXT_TOOL_NAMES:
                results.append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "success": False,
                        "error": "Tool is not available for Agentic context gathering.",
                    }
                )
                continue
            try:
                result = await asyncio.to_thread(registry.call, name, arguments)
                results.append({"tool": name, "arguments": arguments, "success": True, "result": result})
            except Exception as exc:
                results.append({"tool": name, "arguments": arguments, "success": False, "error": str(exc)})
        return results

    def _available_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {}),
            }
            for tool in registry.public_definitions()
            if tool["name"] in CONTEXT_TOOL_NAMES
        ]

    def _max_tool_steps(self) -> int:
        return min(MAX_TOOL_STEPS + 1, effort_tool_steps(self.settings.effort))

    def _max_tool_calls(self) -> int:
        return min(MAX_TOOL_CALLS_PER_STEP + 1, effort_tool_calls(self.settings.effort))

    def _compact_tool_results(self, tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact = []
        for item in tool_results[-8:]:
            rendered = self._render_tool_result(str(item.get("tool") or ""), item.get("result") if item.get("success") else item.get("error"))
            compact.append(
                {
                    "tool": item.get("tool"),
                    "arguments": item.get("arguments"),
                    "success": item.get("success"),
                    "result": rendered[:4_000],
                }
            )
        return compact

    def _format_tool_result(self, item: dict[str, Any]) -> str:
        tool = str(item.get("tool") or "")
        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        if not item.get("success"):
            return (
                f"Tool: {tool}\n"
                f"Arguments: {json.dumps(arguments, ensure_ascii=False)}\n"
                f"Error: {item.get('error', 'unknown error')}"
            )
        rendered = self._render_tool_result(tool, item.get("result"))
        if len(rendered) > MAX_TOOL_RESULT_CHARS:
            rendered = rendered[:MAX_TOOL_RESULT_CHARS].rstrip() + "\n...[tool result truncated]"
        return f"Tool: {tool}\nArguments: {json.dumps(arguments, ensure_ascii=False)}\nResult:\n{rendered}"

    def _render_tool_result(self, tool: str, result: Any) -> str:
        if tool == "nixai_web_fetch_url" and isinstance(result, dict):
            clean_result = dict(result)
            text = _readable_text(str(clean_result.get("text") or ""))
            if len(text) > MAX_FETCH_CHARS:
                text = text[:MAX_FETCH_CHARS].rstrip() + "\n...[source text truncated]"
            clean_result["text"] = text
            return json.dumps(clean_result, ensure_ascii=False, indent=2)
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)

    def _parse_json(self, content: str) -> dict[str, Any]:
        clean = content.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
            clean = re.sub(r"```$", "", clean).strip()
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", clean)
            if not match:
                raise ValueError("Research planner did not return JSON.")
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("Research planner JSON was not an object.")
        return parsed


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _readable_text(text: str) -> str:
    if "<" not in text or ">" not in text:
        return _compact_whitespace(text)
    parser = _TextExtractor()
    try:
        parser.feed(text)
    except Exception:
        return _compact_whitespace(text)
    return _compact_whitespace("".join(parser.parts))


def _compact_whitespace(text: str) -> str:
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    compact_lines = [line for line in lines if line]
    return "\n".join(compact_lines)
