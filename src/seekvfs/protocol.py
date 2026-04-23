"""Protocol interfaces: BackendProtocol + Reranker.

The core protocol deliberately does NOT define ``Summarizer`` or
``Embedder`` — how (and whether) a backend derives short forms of its
entries or embeds them for retrieval is an implementation detail. If
you want a drop-in tiered backend, see :mod:`seekvfs_recipes.maximal`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from seekvfs.models import (
    FileData,
    FileInfo,
    GrepMatch,
    SearchResult,
)


@runtime_checkable
class Reranker(Protocol):
    """Merges per-backend search results into a unified, ordered list."""

    def merge(
        self,
        per_backend: list[SearchResult],
        limit: int,
    ) -> SearchResult: ...


@runtime_checkable
class BackendProtocol(Protocol):
    """Storage-only backend contract — no tiers, no derivative concepts.

    ``hint`` on ``read`` is a pass-through string; the protocol assigns
    no meaning to any value. Backends that accept hints (e.g. the
    tiered recipe) document their own value set. Backends that don't
    understand a hint should ignore it or raise.
    """

    def write(self, path: str, content: bytes | str) -> None: ...

    def read(
        self,
        path: str,
        hint: str | None = None,
    ) -> FileData: ...

    def read_full(self, path: str) -> FileData: ...

    def search(
        self,
        query: str,
        path_pattern: str | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> SearchResult: ...

    def ls(
        self,
        path: str,
        pattern: str | None = None,
        recursive: bool = False,
    ) -> list[FileInfo]: ...

    def edit(self, path: str, old: str, new: str) -> int: ...

    def grep(
        self,
        pattern: str,
        path_pattern: str | None = None,
    ) -> list[GrepMatch]: ...

    def delete(self, path: str) -> None: ...

    def read_batch(self, paths: list[str]) -> dict[str, FileData]: ...

    def initialize(self) -> None:
        """One-time setup: create tables, directories, or other resources.

        Must be idempotent (safe to call multiple times).
        Implementations without setup state should make this a no-op.
        """
        ...

    def close(self) -> None:
        """Release any resources / wait for any in-flight background work.

        Implementations without background state should make this a no-op.
        """
        ...


__all__ = ["BackendProtocol", "Reranker"]
