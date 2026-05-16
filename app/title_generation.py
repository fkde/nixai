from __future__ import annotations

from app.models import MessageMode
from app.runtime_context import runtime_meta_context


DEFAULT_CHAT_TITLES = {"Neuer Chat", "New Chat"}


def build_chat_title_messages(user_message: str, mode: MessageMode) -> list[dict[str, str]]:
    prompt = (
        "Generate a concise chat title for the user's request.\n"
        "Rules:\n"
        "- Return only the title.\n"
        "- 2 to 6 words.\n"
        "- Match the user's language.\n"
        "- No quotes, no markdown, no trailing punctuation.\n"
        "- Prefer a useful summary over copying the full sentence.\n\n"
        f"Mode: {mode}\n"
        f"User request: {user_message}"
    )
    return [
        {
            "role": "system",
            "content": f"{runtime_meta_context(user_message)}\n\nYou write short app sidebar titles. Return plain text only.",
        },
        {"role": "user", "content": prompt},
    ]


def clean_chat_title(title: object, *, max_length: int = 56, max_words: int | None = None) -> str:
    clean = " ".join(str(title or "").strip().split())
    clean = clean.strip("\"'`“”„")
    clean = clean.removeprefix("- ").removeprefix("* ").strip()
    clean = clean.rstrip(".:;")
    if not clean or clean in DEFAULT_CHAT_TITLES:
        return ""
    if max_words is not None:
        words = clean.split()
        if len(words) > max_words:
            clean = " ".join(words[:max_words])
    return clean[:max_length]
