from __future__ import annotations

from app.title_generation import build_chat_title_messages, clean_chat_title


def test_clean_chat_title_removes_markup_and_punctuation() -> None:
    assert clean_chat_title('  "- Analyse NixAI Tests."  ') == "Analyse NixAI Tests"
    assert clean_chat_title("* Build Workflow Runner:") == "Build Workflow Runner"
    assert clean_chat_title("New Chat") == ""


def test_clean_chat_title_can_limit_words() -> None:
    assert clean_chat_title("One two three four five", max_words=3) == "One two three"


def test_build_chat_title_messages_contains_mode_and_request() -> None:
    messages = build_chat_title_messages("Bitte teste die App", "code")

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "Return plain text only" in messages[0]["content"]
    assert "Mode: code" in messages[1]["content"]
    assert "Bitte teste die App" in messages[1]["content"]
