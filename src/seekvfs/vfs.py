"""Top-level VFS facade.

Protocol-layer responsibilities only:

- URI parsing + longest-prefix routing
- Cross-backend search fan-out + reranker merge
- Tool export
- Lifecycle forwarding (``close``)

No tier concepts, no derivative scheduling, no summarizer / embedder
injection — those all live inside backend implementations (see e.g.
:mod:`seekvfs_recipes.maximal`).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from seekvfs.exceptions import InvalidRouteConfig, VFSError
from seekvfs.models import (
    FileData,
    FileInfo,
    GrepMatch,
    RouteConfig,
    SearchResult,
)
from seekvfs.reranker import LinearReranker
from seekvfs.router import Router
from seekvfs.uri import SCHEME

if TYPE_CHECKING:
    from seekvfs.protocol import Reranker
    from seekvfs.tools import Tool


@contextmanager
def _instrument_vfs(name: str) -> Iterator[None]:
    try:
        import logfire
    except ImportError:
        yield
        return

    with logfire.span(name):
        yield


class VFS:
    """Unified front door for SeekVFS storage protocol."""

    def __init__(
        self,
        routes: dict[str, RouteConfig],
        reranker: Reranker | None = None,
        scheme: str = SCHEME,
    ) -> None:
        self._scheme = scheme
        normalized = {self._normalize(k): v for k, v in routes.items()}
        self._validate_routes(normalized)
        self._routes = normalized
        self._router = Router(normalized)
        self._reranker: Reranker = reranker or LinearReranker()

    def _normalize(self, path: str) -> str:
        """Ensure *path* carries the configured scheme.

        * Already starts with the configured scheme → returned as-is (idempotent).
        * Bare path with no ``://`` → the configured scheme is prepended.
        * Contains ``://`` but a different scheme → raises :class:`VFSError`.
        """
        if path.startswith(self._scheme):
            return path
        if "://" in path:
            raise VFSError(
                f"path uses an unknown scheme; expected {self._scheme!r}, got {path!r}"
            )
        return self._scheme + path

    def _validate_routes(self, routes: dict[str, RouteConfig]) -> None:
        if not routes:
            raise InvalidRouteConfig("routes must be a non-empty dict")
        for key, cfg in routes.items():
            if not key.startswith(self._scheme):
                raise InvalidRouteConfig(
                    f"route key must start with {self._scheme!r}, got {key!r}"
                )
            if "backend" not in cfg:
                raise InvalidRouteConfig(f"route {key!r} missing 'backend'")

    # ---------- main API ----------

    def write(self, path: str, content: bytes | str) -> None:
        with _instrument_vfs("vfs.write"):
            path = self._normalize(path)
            _, route = self._router.resolve(path)
            route["backend"].write(path, content)

    def read(self, path: str, hint: str | None = None) -> FileData:
        with _instrument_vfs("vfs.read"):
            path = self._normalize(path)
            _, route = self._router.resolve(path)
            return route["backend"].read(path, hint=hint)

    def read_full(self, path: str) -> FileData:
        with _instrument_vfs("vfs.read_full"):
            path = self._normalize(path)
            _, route = self._router.resolve(path)
            return route["backend"].read_full(path)

    def search(
        self,
        query: str,
        path_pattern: str | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> SearchResult:
        """Fan out across every route sequentially, then rerank."""
        with _instrument_vfs("vfs.search"):
            routes = self._router.all_routes()
            if not routes:
                return SearchResult(query=query, hits=[], searched_paths=[])

            per_backend: list[SearchResult] = []
            for prefix, route in routes:
                out = route["backend"].search(
                    query,
                    path_pattern=path_pattern,
                    limit=limit,
                    score_threshold=score_threshold,
                )
                if prefix not in out.searched_paths:
                    out.searched_paths.append(prefix)
                per_backend.append(out)

            return self._reranker.merge(per_backend, limit=limit)

    def ls(
        self,
        path: str,
        pattern: str | None = None,
        recursive: bool = False,
    ) -> list[FileInfo]:
        with _instrument_vfs("vfs.ls"):
            path = self._normalize(path)
            _, route = self._router.resolve(path)
            return route["backend"].ls(path, pattern=pattern, recursive=recursive)

    def edit(self, path: str, old: str, new: str) -> int:
        with _instrument_vfs("vfs.edit"):
            path = self._normalize(path)
            _, route = self._router.resolve(path)
            return route["backend"].edit(path, old, new)

    def grep(
        self,
        pattern: str,
        path_pattern: str | None = None,
    ) -> list[GrepMatch]:
        with _instrument_vfs("vfs.grep"):
            results: list[GrepMatch] = []
            for _, route in self._router.all_routes():
                results.extend(route["backend"].grep(pattern, path_pattern=path_pattern))
            return results

    def delete(self, path: str) -> None:
        with _instrument_vfs("vfs.delete"):
            path = self._normalize(path)
            _, route = self._router.resolve(path)
            route["backend"].delete(path)

    def read_batch(self, paths: list[str]) -> dict[str, FileData]:
        by_backend: dict[int, tuple[object, list[str]]] = {}
        for p in paths:
            p = self._normalize(p)
            _, route = self._router.resolve(p)
            b = route["backend"]
            key = id(b)
            by_backend.setdefault(key, (b, []))[1].append(p)

        out: dict[str, FileData] = {}
        for _, (backend, sub_paths) in by_backend.items():
            partial = backend.read_batch(sub_paths)  # type: ignore[attr-defined]
            out.update(partial)
        return out

    # ---------- introspection ----------

    def iter_routes(self) -> list[tuple[str, RouteConfig]]:
        """Return ``(prefix, RouteConfig)`` pairs, sorted by prefix length
        descending (same order used by longest-prefix resolution).
        """
        return self._router.all_routes()

    # ---------- tools ----------

    @property
    def tools(self) -> list[Tool]:
        from seekvfs.tools import build_tools

        return build_tools(self)

    # ---------- lifecycle ----------

    def initialize(self) -> None:
        """Forward to every backend's ``initialize`` (if the backend exposes one).

        Safe to call even when no backend requires setup; backends without
        setup state simply return immediately.  Called automatically by
        ``__enter__`` when used as a context manager.
        """
        seen: set[int] = set()
        for _, route in self._router.all_routes():
            backend = route["backend"]
            if id(backend) in seen:
                continue
            seen.add(id(backend))
            init = getattr(backend, "initialize", None)
            if init is not None:
                init()

    def close(self) -> None:
        """Forward to every backend's ``close`` (if the backend exposes one).

        Safe to call even when no backend has background state; backends
        with no resources simply return immediately.
        """
        seen: set[int] = set()
        for _, route in self._router.all_routes():
            backend = route["backend"]
            if id(backend) in seen:
                continue
            seen.add(id(backend))
            close = getattr(backend, "close", None)
            if close is None:
                continue
            close()

    def __enter__(self) -> VFS:
        self.initialize()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["VFS"]
