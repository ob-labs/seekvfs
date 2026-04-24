"""Convert Tool list to Anthropic tool-use format."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from seekvfs.tools.spec import Tool


def to_anthropic(tools: Sequence[Tool]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.args_model.model_json_schema(),
        }
        for tool in tools
    ]


__all__ = ["to_anthropic"]
