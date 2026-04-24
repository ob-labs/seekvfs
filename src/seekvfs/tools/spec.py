"""Neutral Tool model and the 8 agent-facing tool builders.

Each built tool is an async callable bound to a :class:`VFS` instance.
Output of read-like tools is wrapped as ``<file path=...>...</file>`` so
agents can clearly distinguish file content from chat text.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from inspect import getdoc, signature
from typing import TYPE_CHECKING, Annotated, Any, get_type_hints, overload

from pydantic import BaseModel, ConfigDict, Field, create_model

from seekvfs.models import FileData

if TYPE_CHECKING:
    from seekvfs.vfs import VFS


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    callable: Callable[..., Any]

    @classmethod
    def from_callable(
        cls,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Tool:
        from seekvfs.vfs import VFS

        tool_name = name or func.__name__.removeprefix("_")
        tool_description = description or getdoc(func)
        if not tool_description:
            raise TypeError(f"Missing tool description for {func.__name__}")

        hints = get_type_hints(
            func,
            globalns={**func.__globals__, "VFS": VFS},
            include_extras=True,
        )
        fields: dict[str, Any] = {}
        for parameter in signature(func).parameters.values():
            if parameter.name == "vfs":
                continue
            if parameter.name not in hints:
                raise TypeError(
                    f"Missing type annotation for tool parameter {func.__name__}.{parameter.name}"
                )
            fields[parameter.name] = (
                hints[parameter.name],
                ... if parameter.default is parameter.empty else parameter.default,
            )

        model_name = "".join(part.capitalize() for part in tool_name.split("_")) + "Args"
        return cls(
            name=tool_name,
            description=tool_description,
            args_model=create_model(
                model_name,
                __config__=ConfigDict(extra="forbid"),
                **fields,
            ),
            callable=func,
        )

    def bind(self, vfs: VFS, route_hint: str = "") -> Tool:
        def _call(**kwargs: Any) -> Any:
            payload = self.args_model(**kwargs)
            return self.callable(vfs, **payload.model_dump())

        return Tool(
            name=f"vfs_{self.name}",
            description=self.description + route_hint,
            args_model=self.args_model,
            callable=_call,
        )


# ---------- helpers ----------


@overload
def toolspec(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
) -> Tool: ...


@overload
def toolspec(
    func: None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[[Callable[..., Any]], Tool]: ...


def toolspec(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Tool | Callable[[Callable[..., Any]], Tool]:
    """Register a tool implementation."""

    def decorator(func: Callable[..., Any]) -> Tool:
        return Tool.from_callable(func, name=name, description=description)

    if func is not None:
        return decorator(func)
    return decorator


def _wrap_file_output(fd: FileData, path: str) -> str:
    text = fd.content.decode("utf-8", errors="replace")
    return f'<file path="{path}">\n{text}\n</file>'


# ---------- tool callable wrappers ----------

@toolspec
def _search(
    vfs: VFS,
    query: Annotated[str, Field(description="Search query")],
    limit: Annotated[int, Field(description="Max hits")] = 10,
) -> dict[str, Any]:
    """Search across files.

    Returns matching paths with a short snippet when the backend provides one.
    If a snippet is insufficient, call read_full(path) for complete content.
    """
    sr = vfs.search(query, limit=limit)
    return {
        "query": sr.query,
        "hits": [
            {
                "path": h.path,
                "snippet": h.snippet,
                "score": h.score,
            }
            for h in sr.hits
        ],
        "searched_paths": sr.searched_paths,
    }


@toolspec
def _read(vfs: VFS, path: Annotated[str, Field(description="Full seekvfs:// URI")]) -> str:
    """Read the backend's preferred representation of a file.

    May be a derived summary if the backend keeps one, or the full content
    otherwise. For the guaranteed original content, call read_full(path).
    """
    fd = vfs.read(path)
    return _wrap_file_output(fd, path)


@toolspec
def _read_full(
    vfs: VFS,
    path: Annotated[str, Field(description="Full seekvfs:// URI")],
) -> str:
    """Read complete original content."""
    fd = vfs.read_full(path)
    return _wrap_file_output(fd, path)


@toolspec
def _write(
    vfs: VFS,
    path: Annotated[str, Field(description="Full seekvfs:// URI")],
    content: Annotated[str, Field(description="File content")],
) -> str:
    """Write content. Indexing behavior is backend-defined."""
    vfs.write(path, content)
    return f"wrote {path}"


@toolspec
def _edit(
    vfs: VFS,
    path: Annotated[str, Field(description="Full seekvfs:// URI")],
    old: Annotated[str, Field(description="Literal text to replace")],
    new: Annotated[str, Field(description="Replacement text")],
) -> str:
    """Literal string replacement. Last-write-wins on concurrent edits."""
    n = vfs.edit(path, old, new)
    return f"{n} replacement(s) in {path}"


@toolspec
def _ls(
    vfs: VFS,
    path: Annotated[str, Field(description="Directory URI")],
    pattern: Annotated[str | None, Field(description="Optional glob, e.g. *.md")] = None,
    recursive: Annotated[bool, Field(description="Recurse into subdirs")] = False,
) -> list[dict[str, Any]]:
    """List files.

    pattern supports glob wildcards such as '*.md'; recursive=True lists the
    full subtree.
    """
    infos = vfs.ls(path, pattern=pattern, recursive=recursive)
    return [
        {
            "path": i.path,
            "size": i.size,
            "is_dir": i.is_dir,
            "snippet": i.snippet,
        }
        for i in infos
    ]


@toolspec
def _grep(
    vfs: VFS,
    pattern: Annotated[str, Field(description="Literal substring")],
    path_pattern: Annotated[
        str | None,
        Field(description="Optional glob to filter paths"),
    ] = None,
) -> list[dict[str, Any]]:
    """Literal search in file contents."""
    matches = vfs.grep(pattern, path_pattern=path_pattern)
    return [
        {"path": m.path, "line_number": m.line_number, "line": m.line}
        for m in matches
    ]


@toolspec
def _delete(
    vfs: VFS,
    path: Annotated[str, Field(description="Full seekvfs:// URI")],
) -> str:
    """Delete a file by path."""
    vfs.delete(path)
    return f"deleted {path}"


_BUILTIN_TOOLS: tuple[Tool, ...] = (
    _search,
    _read,
    _read_full,
    _write,
    _edit,
    _ls,
    _grep,
    _delete,
)


def _route_suffix(vfs: VFS) -> str:
    """Build a route-context hint appended to every tool description.

    Lets agents construct correct full URIs without needing an external system
    prompt — the routing information travels with the tools themselves.

    seekvfs:// is the fixed scheme for all routes; only the distinguishing
    path segments are listed to avoid redundancy.

    Example output (two routes):
        Scheme: seekvfs://  Routes: notes/, docs/
        Always use a full URI (e.g. 'seekvfs://notes/hello.md').
    """
    prefixes = [prefix for prefix, _ in vfs.iter_routes()]
    if not prefixes:
        return ""
    from seekvfs.uri import SCHEME
    segments = ", ".join(p.removeprefix(SCHEME) for p in prefixes)
    example = prefixes[0] + "hello.md"
    return (
        f"\nScheme: {SCHEME}  Routes: {segments}"
        f"\nAlways use a full URI (e.g. {example!r})."
        " Bare filenames without a route prefix are invalid."
    )


def build_tools(vfs: VFS) -> list[Tool]:
    """Produce the 8 agent-facing tools bound to ``vfs``.

    All tool names carry a ``vfs_`` prefix (e.g. ``vfs_read``, ``vfs_write``)
    so they never clash with generic file-system tools that an agent may also
    have access to (e.g. ``read_file``, ``write_file``).
    """
    route_hint = _route_suffix(vfs)
    return [tool.bind(vfs, route_hint) for tool in _BUILTIN_TOOLS]


__all__ = ["Tool", "build_tools", "toolspec"]
