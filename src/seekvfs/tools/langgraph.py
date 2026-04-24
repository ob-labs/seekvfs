"""Convert ToolSpecSet to LangGraph / LangChain StructuredTool list.

Soft-depends on ``langchain-core``; raises an informative ``ImportError`` if
missing, directing the user to the ``[langgraph]`` extra.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, create_model

from seekvfs.tools.spec import ToolSpec, ToolSpecSet

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _build_args_schema(spec: ToolSpec) -> type[BaseModel]:
    """Build a Pydantic BaseModel from the tool's JSON schema.

    ``functools.partial`` objects are not accepted by
    ``langchain_core``'s ``validate_arguments``, so we provide an
    explicit ``args_schema`` instead of relying on signature inference.
    """
    schema = spec.parameters_schema
    properties: dict[str, Any] = schema.get("properties", {})
    required: set[str] = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for field_name, field_info in properties.items():
        py_type = _JSON_TYPE_MAP.get(field_info.get("type", "string"), str)
        if field_name in required:
            fields[field_name] = (py_type, ...)
        else:
            default = field_info.get("default", None)
            fields[field_name] = (py_type | None, default)

    return create_model(spec.name, **fields)


def _require_langchain():
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as e:  # pragma: no cover - import guard
        raise ImportError(
            "to_langgraph requires `langchain-core`. "
            "Install with: pip install langchain-core langgraph"
        ) from e
    return StructuredTool


def _to_tool(StructuredTool: Any, spec: ToolSpec) -> Any:  # noqa: N803
    args_schema = _build_args_schema(spec)
    fn = spec.callable

    # Wrap the partial in a plain function so StructuredTool.from_function
    # does not attempt get_type_hints() on a functools.partial object.
    def _wrapper(**kwargs: Any) -> Any:
        return fn(**kwargs)

    _wrapper.__name__ = spec.name

    return StructuredTool.from_function(
        func=_wrapper,
        name=spec.name,
        description=spec.description,
        args_schema=args_schema,
    )


def to_langgraph(specs: ToolSpecSet) -> list[Any]:
    StructuredTool = _require_langchain()
    return [_to_tool(StructuredTool, s) for s in specs.specs]


__all__ = ["to_langgraph"]
