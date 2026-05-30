from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient


def patch_agent(monkeypatch, fake_ollama):
    from app.agent import Agent
    from app.api import chats as chats_api

    monkeypatch.setattr(chats_api, "Agent", lambda effort=None: Agent(ollama=fake_ollama, effort=effort))
    return chats_api


def test_chat_routes_cover_create_update_messages_and_delete(db, monkeypatch, fake_ollama) -> None:
    chats_api = patch_agent(monkeypatch, fake_ollama)
    app = FastAPI()
    app.include_router(chats_api.router)
    client = TestClient(app)

    response = client.post("/api/chats", json={"title": "  API Chat  ", "workspace_path": ""})
    assert response.status_code == 200
    chat = response.json()
    assert chat["title"] == "API Chat"

    response = client.put(f"/api/chats/{chat['id']}", json={"title": "Renamed", "workspace_path": ""})
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"

    response = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Hello API", "mode": "chat"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_message"]["content"] == "Hello API"
    assert payload["assistant_message"]["content"] == "Fake stream response."
    assert fake_ollama.stream_chat_calls

    response = client.get(f"/api/chats/{chat['id']}/messages")
    assert response.status_code == 200
    assert [item["role"] for item in response.json()] == ["user", "assistant"]

    response = client.delete(f"/api/chats/{chat['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/chats/{chat['id']}").status_code == 404


def test_chat_stream_route_uses_fake_ollama_chunks(db, monkeypatch, fake_ollama) -> None:
    chats_api = patch_agent(monkeypatch, fake_ollama)
    app = FastAPI()
    app.include_router(chats_api.router)
    client = TestClient(app)

    chat = db.create_chat("Stream")
    with client.stream(
        "POST",
        f"/api/chats/{chat.id}/messages/stream",
        json={"content": "Stream please", "mode": "chat"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"type": "token"' in body
    assert "Fake stream response." in body
    assert fake_ollama.stream_chat_calls


def test_agent_run_uses_fake_ollama_without_network(db, fake_ollama) -> None:
    from app.agent import Agent

    chat = db.create_chat("Agent")
    response = asyncio.run(Agent(ollama=fake_ollama).run(chat.id, "Hello Agent", mode="chat"))

    assert response.assistant_message.content == "Fake stream response."
    assert fake_ollama.stream_chat_calls


def test_agent_run_and_stream_produce_same_final_assistant_message(db) -> None:
    from app.agent import Agent
    from tests.fakes.ollama import FakeOllamaClient

    async def scenario() -> tuple[str, str]:
        run_client = FakeOllamaClient(stream_chunks=["Same ", "answer."])
        stream_client = FakeOllamaClient(stream_chunks=["Same ", "answer."])
        run_chat = db.create_chat("Run")
        stream_chat = db.create_chat("Stream")

        run_response = await Agent(ollama=run_client).run(run_chat.id, "Hello Agent", mode="chat")

        streamed_answer = ""
        async for event in Agent(ollama=stream_client).stream(stream_chat.id, "Hello Agent", mode="chat"):
            if event.get("type") == "assistant_message":
                streamed_answer = str(event["message"]["content"])

        return run_response.assistant_message.content, streamed_answer

    run_answer, stream_answer = asyncio.run(scenario())

    assert run_answer == stream_answer == "Same answer."


def test_chat_routes_return_errors_for_missing_chat_and_invalid_message(db, monkeypatch, fake_ollama) -> None:
    chats_api = patch_agent(monkeypatch, fake_ollama)
    app = FastAPI()
    app.include_router(chats_api.router)
    client = TestClient(app)

    assert client.get("/api/chats/missing").status_code == 404
    assert client.get("/api/chats/missing/messages").status_code == 404
    assert client.post("/api/chats/missing/messages", json={"content": "Hello"}).status_code == 404
    assert client.post("/api/chats/missing/messages", json={"content": ""}).status_code == 422
