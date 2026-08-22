"""Server-Sent Event serialization helpers."""

from __future__ import annotations

import json
from typing import Any


def sse_json(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"data: {data}\n\n".encode()


def sse_done() -> bytes:
    return b"data: [DONE]\n\n"
