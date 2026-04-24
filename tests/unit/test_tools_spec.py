from __future__ import annotations

from seekvfs.tools import Tool, build_tools
from seekvfs.vfs import VFS
from tests.conftest import _StubBackend


def _vfs() -> VFS:
    return VFS(routes={"seekvfs://mem/": {"backend": _StubBackend()}})


def _by_name(tools: list[Tool]) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}


def test_eight_tools_present() -> None:
    tools = build_tools(_vfs())
    expected = [
        "vfs_search",
        "vfs_read",
        "vfs_read_full",
        "vfs_write",
        "vfs_edit",
        "vfs_ls",
        "vfs_grep",
        "vfs_delete",
    ]
    assert [tool.name for tool in tools] == expected


def test_schema_structure() -> None:
    for tool in build_tools(_vfs()):
        schema = tool.args_model.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema


def test_write_read_roundtrip_via_tools() -> None:
    tools = _by_name(build_tools(_vfs()))
    tools["vfs_write"].callable(path="seekvfs://mem/a", content="hello")
    out = tools["vfs_read"].callable(path="seekvfs://mem/a")
    assert 'path="seekvfs://mem/a"' in out
    assert "hello" in out
    assert "returned_level" not in out


def test_search_tool_returns_shape() -> None:
    tools = _by_name(build_tools(_vfs()))
    tools["vfs_write"].callable(path="seekvfs://mem/a", content="alpha beta")
    result = tools["vfs_search"].callable(query="alpha", limit=3)
    assert "hits" in result
    assert "searched_paths" in result
    if result["hits"]:
        assert "snippet" in result["hits"][0]
        assert "level" not in result["hits"][0]


def test_ls_tool() -> None:
    tools = _by_name(build_tools(_vfs()))
    tools["vfs_write"].callable(path="seekvfs://mem/a", content="x")
    rows = tools["vfs_ls"].callable(path="seekvfs://mem/")
    assert any(r["path"] == "seekvfs://mem/a" for r in rows)
    assert all("snippet" in r for r in rows)
