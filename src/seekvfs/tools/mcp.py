"""Convert Tool list to an MCP server instance.

Soft-depends on ``mcp``; raises an informative ``ImportError`` if missing.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from seekvfs.tools.spec import Tool


def _require_mcp():
    try:
        from mcp.server import Server
        from mcp.types import Tool as MCPTool
    except ImportError as e:  # pragma: no cover - import guard
        raise ImportError(
            "to_mcp requires `mcp`. Install with: pip install 'seekvfs[mcp]'"
        ) from e
    return Server, MCPTool


def to_mcp(tools: Sequence[Tool], server_name: str = "seekvfs") -> Any:
    Server, MCPTool = _require_mcp()
    server = Server(server_name)
    tool_map = {tool.name: tool for tool in tools}

    mcp_tools = [
        MCPTool(
            name=tool.name,
            description=tool.description,
            inputSchema=tool.args_model.model_json_schema(),
        )
        for tool in tools
    ]

    @server.list_tools()
    async def _list_tools() -> list[Any]:
        return mcp_tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> Any:
        return tool_map[name].callable(**(arguments or {}))

    return server


__all__ = ["to_mcp"]
