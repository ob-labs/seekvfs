"""Neutral ToolSpec + ToolSpecSet and the 8 agent-facing tool builders.

Each built tool is an async callable bound to a :class:`VFS` instance.
Output of read-like tools is wrapped as ``<file path=...>...</file>`` so
agents can clearly distinguish file content from chat text.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import partial
from typing import TYPE_CHECKING, Any

from seekvfs.models import FileData

if TYPE_CHECKING:
    from seekvfs.vfs import VFS


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    callable: Callable[..., Any]


@dataclass
class ToolSpecSet:
    specs: list[ToolSpec] = field(default_factory=list)

    # ---- ergonomics ----

    def __iter__(self):
        return iter(self.specs)

    def __len__(self) -> int:
        return len(self.specs)

    def names(self) -> list[str]:
        return [s.name for s in self.specs]

    def by_name(self, name: str) -> ToolSpec:
        for s in self.specs:
            if s.name == name:
                return s
        raise KeyError(name)

    def with_description_overrides(
        self, overrides: dict[str, str]
    ) -> ToolSpecSet:
        new_specs: list[ToolSpec] = []
        for s in self.specs:
            if s.name in overrides:
                new_specs.append(replace(s, description=overrides[s.name]))
            else:
                new_specs.append(s)
        return ToolSpecSet(specs=new_specs)

    # ---- framework converters ----

    def to_openai(self) -> list[dict[str, Any]]:
        from seekvfs.tools.openai import to_openai

        return to_openai(self)

    def to_anthropic(self) -> list[dict[str, Any]]:
        from seekvfs.tools.anthropic import to_anthropic

        return to_anthropic(self)

    def to_langgraph(self) -> list[Any]:
        from seekvfs.tools.langgraph import to_langgraph

        return to_langgraph(self)

    def to_mcp(self) -> Any:
        from seekvfs.tools.mcp import to_mcp

        return to_mcp(self)


# ---------- helpers ----------


def _wrap_file_output(fd: FileData, path: str) -> str:
    text = fd.content.decode("utf-8", errors="replace")
    return f'<file path="{path}">\n{text}\n</file>'


# ---------- tool callable wrappers ----------

def _search(vfs: VFS, query: str, limit: int = 10) -> dict[str, Any]:
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


def _read(vfs: VFS, path: str) -> str:
    fd = vfs.read(path)
    return _wrap_file_output(fd, path)


def _read_full(vfs: VFS, path: str) -> str:
    fd = vfs.read_full(path)
    return _wrap_file_output(fd, path)


def _write(vfs: VFS, path: str, content: str) -> str:
    vfs.write(path, content)
    return f"wrote {path}"


def _edit(vfs: VFS, path: str, old: str, new: str) -> str:
    n = vfs.edit(path, old, new)
    return f"{n} replacement(s) in {path}"


def _ls(
    vfs: VFS,
    path: str,
    pattern: str | None = None,
    recursive: bool = False,
) -> list[dict[str, Any]]:
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


def _grep(
    vfs: VFS,
    pattern: str,
    path_pattern: str | None = None,
) -> list[dict[str, Any]]:
    matches = vfs.grep(pattern, path_pattern=path_pattern)
    return [
        {"path": m.path, "line_number": m.line_number, "line": m.line}
        for m in matches
    ]


def _delete(vfs: VFS, path: str) -> str:
    vfs.delete(path)
    return f"deleted {path}"


# ---------- schemas ----------

def _schema(**props: dict[str, Any]) -> dict[str, Any]:
    required = [k for k, v in props.items() if v.pop("_required", True)]
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


_DESCRIPTIONS: dict[str, str] = {
    "search": (
        "Search across files. Returns matching paths with a short snippet "
        "(when the backend provides one). If a snippet is insufficient, "
        "call read_full(path) for complete content."
    ),
    "read": (
        "Read the backend's preferred representation of a file. May be a "
        "derived summary if the backend keeps one, or the full content "
        "otherwise. For the guaranteed original content, call read_full(path)."
    ),
    "read_full": "Read complete original content.",
    "write": "Write content. Indexing behavior is backend-defined.",
    "edit": "Literal string replacement. Last-write-wins on concurrent edits.",
    "ls": (
        "List files. pattern supports glob wildcards (e.g. '*.md'); "
        "recursive=True lists subtree."
    ),
    "grep": "Literal search in file contents.",
    "delete": "Delete a file by path.",
}


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


def build_tools(vfs: VFS) -> ToolSpecSet:
    """Produce the 8 agent-facing tools bound to ``vfs``.

    All tool names carry a ``vfs_`` prefix (e.g. ``vfs_read``, ``vfs_write``)
    so they never clash with generic file-system tools that an agent may also
    have access to (e.g. ``read_file``, ``write_file``).
    """
    route_hint = _route_suffix(vfs)
    specs = [
        ToolSpec(
            name="vfs_search",
            description=_DESCRIPTIONS["search"] + route_hint,
            parameters_schema=_schema(
                query={"type": "string", "description": "Search query"},
                limit={
                    "type": "integer",
                    "description": "Max hits",
                    "default": 10,
                    "_required": False,
                },
            ),
            callable=partial(_search, vfs),
        ),
        ToolSpec(
            name="vfs_read",
            description=_DESCRIPTIONS["read"] + route_hint,
            parameters_schema=_schema(
                path={"type": "string", "description": "Full seekvfs:// URI"},
            ),
            callable=partial(_read, vfs),
        ),
        ToolSpec(
            name="vfs_read_full",
            description=_DESCRIPTIONS["read_full"] + route_hint,
            parameters_schema=_schema(
                path={"type": "string", "description": "Full seekvfs:// URI"},
            ),
            callable=partial(_read_full, vfs),
        ),
        ToolSpec(
            name="vfs_write",
            description=_DESCRIPTIONS["write"] + route_hint,
            parameters_schema=_schema(
                path={"type": "string", "description": "Full seekvfs:// URI"},
                content={"type": "string", "description": "File content"},
            ),
            callable=partial(_write, vfs),
        ),
        ToolSpec(
            name="vfs_edit",
            description=_DESCRIPTIONS["edit"] + route_hint,
            parameters_schema=_schema(
                path={"type": "string", "description": "Full seekvfs:// URI"},
                old={"type": "string", "description": "Literal text to replace"},
                new={"type": "string", "description": "Replacement text"},
            ),
            callable=partial(_edit, vfs),
        ),
        ToolSpec(
            name="vfs_ls",
            description=_DESCRIPTIONS["ls"] + route_hint,
            parameters_schema=_schema(
                path={"type": "string", "description": "Directory URI"},
                pattern={
                    "type": "string",
                    "description": "Optional glob, e.g. *.md",
                    "_required": False,
                },
                recursive={
                    "type": "boolean",
                    "description": "Recurse into subdirs",
                    "default": False,
                    "_required": False,
                },
            ),
            callable=partial(_ls, vfs),
        ),
        ToolSpec(
            name="vfs_grep",
            description=_DESCRIPTIONS["grep"] + route_hint,
            parameters_schema=_schema(
                pattern={"type": "string", "description": "Literal substring"},
                path_pattern={
                    "type": "string",
                    "description": "Optional glob to filter paths",
                    "_required": False,
                },
            ),
            callable=partial(_grep, vfs),
        ),
        ToolSpec(
            name="vfs_delete",
            description=_DESCRIPTIONS["delete"] + route_hint,
            parameters_schema=_schema(
                path={"type": "string", "description": "Full seekvfs:// URI"},
            ),
            callable=partial(_delete, vfs),
        ),
    ]
    return ToolSpecSet(specs=specs)


__all__ = ["ToolSpec", "ToolSpecSet", "build_tools"]
