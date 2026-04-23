"""File-system backend: :class:`FileBackend`.

Stores one file per VFS path under a local directory tree. No summaries,
no embeddings — the simplest *persistent* backend that satisfies
:class:`seekvfs.BackendProtocol`.

Every VFS path is mapped to a local file by stripping the ``seekvfs://``
scheme prefix (if present) and appending to *root_dir*::

    seekvfs://notes/a.md  →  {root_dir}/notes/a.md
    notes/a.md            →  {root_dir}/notes/a.md

Scan results (``ls``, ``search``, ``grep``) preserve the scheme format of
the input path — callers that use ``seekvfs://`` URIs get URIs back,
callers that use plain relative paths get plain paths back.  When no path
context is available (e.g. ``search`` with no ``path_pattern``), the
``seekvfs://`` scheme is used by default, which is the correct behaviour
when called through :class:`seekvfs.VFS`.

Full usage / adaptation guide: ``docs/recipes/minimal.md``.
"""
from __future__ import annotations

import fnmatch
import threading
from datetime import UTC, datetime
from pathlib import Path

from seekvfs.exceptions import NotFoundError
from seekvfs.models import (
    FileData,
    FileInfo,
    GrepMatch,
    SearchHit,
    SearchResult,
)
from seekvfs.uri import SCHEME as _SCHEME


def _to_bytes(content: bytes | str) -> bytes:
    return content if isinstance(content, bytes) else content.encode("utf-8")


def _detect_scheme(*paths: str | None) -> str:
    """Return ``'seekvfs://'`` if the first non-None path uses it, else ``''``.

    Falls back to ``'seekvfs://'`` when all inputs are ``None`` — correct for
    the VFS-call scenario where no path context is available.
    """
    for p in paths:
        if p is not None:
            return _SCHEME if p.startswith(_SCHEME) else ""
    return _SCHEME


class FileBackend:
    """Minimal persistent backend: one file per VFS path on local disk.

    Args:
        root_dir: Root directory for all stored files. Created automatically
            if it does not already exist.
    """

    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir).resolve()
        self._edit_lock = threading.Lock()

    # ---------- internal helpers ----------

    def _local(self, path: str) -> Path:
        """Map a VFS path (with or without scheme) to a local ``Path``."""
        rel = path.removeprefix(_SCHEME)
        return self._root / rel

    def _reconstruct(self, fp: Path, scheme: str) -> str:
        """Reconstruct the VFS path for a local file."""
        rel = str(fp.relative_to(self._root))
        return scheme + rel

    # ---------- writes ----------

    def write(self, path: str, content: bytes | str) -> None:
        data = _to_bytes(content)
        fp = self._local(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(data)

    # ---------- reads ----------

    def read(self, path: str, hint: str | None = None) -> FileData:
        """Read the stored content.

        ``hint`` is accepted and silently ignored — this backend stores
        only one representation per path.
        """
        fp = self._local(path)
        if not fp.exists():
            raise NotFoundError(path)
        return FileData(fp.read_bytes(), "utf-8")

    def read_full(self, path: str) -> FileData:
        return self.read(path)

    def read_batch(self, paths: list[str]) -> dict[str, FileData]:
        return {p: self.read(p) for p in paths}

    # ---------- search ----------

    def search(
        self,
        query: str,
        path_pattern: str | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> SearchResult:
        """Literal substring search across stored files.

        Scores are ``1.0`` for a match, ``0.0`` otherwise (no ranking).
        For vector / semantic search, use :mod:`seekvfs_recipes.maximal`
        with an embedder.
        """
        scheme = _detect_scheme(path_pattern)
        q_low = query.lower()

        hits: list[SearchHit] = []
        searched: list[str] = []
        for fp in self._root.rglob("*"):
            if not fp.is_file():
                continue
            vfs_path = self._reconstruct(fp, scheme)
            if path_pattern is not None and not fnmatch.fnmatch(vfs_path, path_pattern):
                continue
            try:
                data = fp.read_bytes()
            except OSError:
                continue
            searched.append(vfs_path)
            text = data.decode("utf-8", errors="replace")
            score = 1.0 if q_low and q_low in text.lower() else 0.0
            if score_threshold is not None and score < score_threshold:
                continue
            if score <= 0:
                continue
            hits.append(SearchHit(path=vfs_path, snippet="", score=score))
        return SearchResult(query=query, hits=hits[:limit], searched_paths=searched)

    # ---------- listing ----------

    def ls(
        self,
        path: str,
        pattern: str | None = None,
        recursive: bool = False,
    ) -> list[FileInfo]:
        prefix = path if path.endswith("/") else path + "/"
        local_rel = prefix.removeprefix(_SCHEME).rstrip("/")
        local_dir = (self._root / local_rel) if local_rel else self._root

        out: list[FileInfo] = []
        if not local_dir.exists():
            return out
        candidates = local_dir.rglob("*") if recursive else local_dir.iterdir()
        for fp in candidates:
            if not fp.is_file():
                continue
            rest = str(fp.relative_to(local_dir))
            if pattern is not None and not fnmatch.fnmatch(rest, pattern):
                continue
            stat = fp.stat()
            out.append(
                FileInfo(
                    path=prefix + rest,
                    size=stat.st_size,
                    mtime=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    is_dir=False,
                )
            )
        out.sort(key=lambda fi: fi.path)
        return out

    # ---------- edit ----------

    def edit(self, path: str, old: str, new: str) -> int:
        fp = self._local(path)
        with self._edit_lock:
            if not fp.exists():
                raise NotFoundError(path)
            text = fp.read_bytes().decode("utf-8", errors="replace")
            count = text.count(old)
            if count == 0:
                return 0
            fp.write_bytes(text.replace(old, new).encode("utf-8"))
            return count

    # ---------- grep ----------

    def grep(
        self,
        pattern: str,
        path_pattern: str | None = None,
    ) -> list[GrepMatch]:
        scheme = _detect_scheme(path_pattern)
        out: list[GrepMatch] = []
        for fp in self._root.rglob("*"):
            if not fp.is_file():
                continue
            vfs_path = self._reconstruct(fp, scheme)
            if path_pattern is not None and not fnmatch.fnmatch(vfs_path, path_pattern):
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for idx, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    out.append(GrepMatch(path=vfs_path, line_number=idx, line=line))
        return out

    # ---------- delete ----------

    def delete(self, path: str) -> None:
        fp = self._local(path)
        if not fp.exists():
            raise NotFoundError(path)
        fp.unlink()
        parent = fp.parent
        while parent != self._root:
            try:
                parent.rmdir()
                parent = parent.parent
            except OSError:
                break

    # ---------- lifecycle ----------

    def initialize(self) -> None:
        """Create the root directory if it does not already exist."""
        self._root.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        pass


__all__ = ["FileBackend"]
