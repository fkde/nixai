from __future__ import annotations

import os
import time

import pytest

from tests.fakes.ollama import FakeOllamaClient


@pytest.fixture(autouse=True)
def isolated_xdg_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


@pytest.fixture
def db():
    from app import database

    database.init_db()
    return database


@pytest.fixture
def fake_ollama():
    return FakeOllamaClient()


@pytest.fixture(autouse=True)
def block_real_ollama(monkeypatch):
    if os.environ.get("NIXAI_TEST_ALLOW_REAL_OLLAMA") == "1":
        return

    from app.llm.ollama import OllamaClient

    async def blocked_call(*_args, **_kwargs):
        raise AssertionError(
            "Real Ollama calls are disabled in tests. Use the fake_ollama fixture "
            "or set NIXAI_TEST_ALLOW_REAL_OLLAMA=1 for explicit integration runs."
        )

    monkeypatch.setattr(OllamaClient, "chat", blocked_call)
    monkeypatch.setattr(OllamaClient, "chat_payload", blocked_call)
    monkeypatch.setattr(OllamaClient, "stream_chat", blocked_call)
    monkeypatch.setattr(OllamaClient, "stream_payload", blocked_call)
    monkeypatch.setattr(OllamaClient, "list_models", blocked_call)
    monkeypatch.setattr(OllamaClient, "list_model_catalog", blocked_call)


@pytest.fixture
def utc_local_timezone(monkeypatch):
    old_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "UTC")
    if hasattr(time, "tzset"):
        time.tzset()
    yield
    if old_tz is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", old_tz)
    if hasattr(time, "tzset"):
        time.tzset()
