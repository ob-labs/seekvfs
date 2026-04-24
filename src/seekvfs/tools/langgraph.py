"""Convert Tool list to LangGraph / LangChain StructuredTool list.

Soft-depends on ``langchain-core``; raises an informative ``ImportError`` if
missing, directing the user to the ``[langgraph]`` extra.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from seekvfs.tools.spec import Tool


def _require_langchain():
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as e:  # pragma: no cover - import guard
        raise ImportError(
            "to_langgraph requires `langchain-core`. "
            "Install with: pip install langchain-core langgraph"
        ) from e
    return StructuredTool


def _to_tool(StructuredTool: Any, tool: Tool) -> Any:  # noqa: N803
    fn = tool.callable

    # Wrap the partial in a plain function so StructuredTool.from_function
    # does not attempt get_type_hints() on a functools.partial object.
    def _wrapper(**kwargs: Any) -> Any:
        return fn(**kwargs)

    _wrapper.__name__ = tool.name

    return StructuredTool.from_function(
        func=_wrapper,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_model,
    )


def to_langgraph(tools: Sequence[Tool]) -> list[Any]:
    StructuredTool = _require_langchain()
    return [_to_tool(StructuredTool, tool) for tool in tools]


__all__ = ["to_langgraph"]
