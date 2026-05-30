from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi.responses import StreamingResponse


SSE_MEDIA_TYPE = "text/event-stream"
logger = logging.getLogger(__name__)


def normalize_sse_event(event: Mapping[str, Any]) -> str:
    return f"data: {json.dumps(dict(event), ensure_ascii=False)}\n\n"


async def iter_sse_events(events: AsyncIterator[Mapping[str, Any]]) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield normalize_sse_event(event)
    except ValueError as exc:
        yield normalize_sse_event({"type": "error", "message": str(exc)})
    except Exception as exc:
        logger.warning("SSE event stream failed", exc_info=True)
        yield normalize_sse_event({"type": "error", "message": f"Response stream failed: {exc}"})


def sse_response(events: AsyncIterator[Mapping[str, Any]]) -> StreamingResponse:
    return StreamingResponse(iter_sse_events(events), media_type=SSE_MEDIA_TYPE)
