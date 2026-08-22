"""OpenAI model-list response helpers."""

from __future__ import annotations

from typing import Any


def model_list(model_ids: list[str]) -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model", "owned_by": "local-gateway"}
            for model_id in model_ids
        ],
    }
