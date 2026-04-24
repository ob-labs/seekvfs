"""Convert Tool list to OpenAI tool-calling format."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from seekvfs.tools.spec import Tool


def to_openai(tools: Sequence[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.args_model.model_json_schema(),
            },
        }
        for tool in tools
    ]


__all__ = ["to_openai"]
