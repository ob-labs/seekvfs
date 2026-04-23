"""OceanbaseFsBackend — L2 on local filesystem, L0/L1/embedding in OceanBase.

This is the **Maximal recipe** for seekvfs. Storage layout:

- **L2** full content      → local filesystem under ``fs_root``
- **L0** abstract (~100 t) → OceanBase via :class:`VfsStorageDAO`
- **L1** overview (~2k t)  → OceanBase via :class:`VfsStorageDAO`
- **embedding**            → OceanBase via :class:`VfsStorageDAO` (vector column)

All database interactions are delegated to a :class:`~seekvfs_recipes.maximal.dao.VfsStorageDAO`
instance, which you can subclass to adapt the table structure, column names,
or swap the database engine entirely.

Full usage guide: ``docs/recipes/maximal.md``.
"""
from __future__ import annotations

import fnmatch
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from seekvfs.exceptions import BackendError, NotFoundError
from seekvfs.models import FileData, FileInfo, GrepMatch, SearchHit, SearchResult
from seekvfs.uri import SCHEME as _SCHEME
from seekvfs_recipes.maximal.dao import VfsStorageDAO
from seekvfs_recipes.maximal.exceptions import TierNotAvailable
from seekvfs_recipes.maximal.protocol import Embedder, Summarizer

logger = logging.getLogger(__name__)

GenerationMode = Literal["sync", "background"]


def _to_bytes(content: bytes | str) -> bytes:
    return content if isinstance(content, bytes) else content.encode("utf-8")


class OceanbaseFsBackend:
    """Production 3-tier backend: filesystem for L2, OceanBase for L0/L1/embedding.

    Hint values accepted by ``read(path, hint=...)``:

    +----------+----------------------------------------------------------+
    | hint     | behaviour                                                |
    +==========+==========================================================+
    | ``None`` | waterfall: L1 → L0 → truncated L2                       |
    | ``"l0"`` | strict L0; raises ``TierNotAvailable`` if not generated  |
    | ``"l1"`` | strict L1; raises ``TierNotAvailable`` if not generated  |
    | ``"l2"`` | full content (equivalent to ``read_full``)               |
    | other    | ``BackendError``                                         |
    +----------+----------------------------------------------------------+

    Args:
        ob_client: A ``pyobvector.ObVecClient`` instance connected to OceanBase.
        fs_root: Root directory for L2 files. Created automatically if absent.
        summarizer: Produces L0 (``abstract``) and L1 (``overview``) from
            raw content.
        embedder: Embeds the L0 text into a dense vector.
        dao: Optional custom :class:`~seekvfs_recipes.maximal.dao.VfsStorageDAO`.
            Pass a subclass to adapt the schema, column names, or DB engine.
            If omitted, a default ``VfsStorageDAO(ob_client, table)`` is created.
        generation: ``"background"`` (default) — ``write`` returns immediately
            and derivatives are generated in a background thread.
            ``"sync"`` — ``write`` blocks until derivatives are committed.
        fallback_l2_chars: Maximum chars returned as a truncated-L2 fallback
            when no L1/L0 is available yet (default ``8000``).
        table: OceanBase table name passed to the default ``VfsStorageDAO``
            (ignored when a custom ``dao`` is supplied).
        l0_threshold: If content (in chars) is shorter than this, L0 is set
            to the content itself — no LLM call is made.  Default 300.
        l1_threshold: If content is shorter than this, L1 is also set to
            the content itself.  Default 2000.
    """

    def __init__(
        self,
        *,
        ob_client: object,
        fs_root: str | Path,
        summarizer: Summarizer,
        embedder: Embedder,
        dao: VfsStorageDAO | None = None,
        generation: GenerationMode = "background",
        fallback_l2_chars: int = 8000,
        table: str = "vfs_storage",
        l0_threshold: int = 300,
        l1_threshold: int = 2000,
    ) -> None:
        if generation not in ("sync", "background"):
            raise ValueError(
                f"generation must be 'sync' or 'background', got {generation!r}"
            )
        self._dao = dao if dao is not None else VfsStorageDAO(ob_client, table)
        self._fs_root = Path(fs_root).resolve()
        self._summarizer = summarizer
        self._embedder = embedder
        self._generation: GenerationMode = generation
        self._fallback_l2_chars = fallback_l2_chars
        self._l0_threshold = l0_threshold
        self._l1_threshold = l1_threshold
        self._pending: dict[str, threading.Thread] = {}
        self._pending_lock = threading.Lock()
        self._edit_lock = threading.Lock()
        self._initialized = False
        self._init_lock = threading.Lock()

    # ---------- lifecycle ----------

    def initialize(self) -> None:
        """Create the fs_root directory and the DB table if they don't exist.

        Idempotent — safe to call multiple times.  Also called automatically
        on the first backend operation via :meth:`_ensure_ready`.
        """
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._fs_root.mkdir(parents=True, exist_ok=True)
            self._dao.initialize()
            self._initialized = True

    def _ensure_ready(self) -> None:
        """Lazy-init guard: call ``initialize()`` on first use."""
        self.initialize()

    # ---------- path helpers ----------

    def _local(self, path: str) -> Path:
        """Map a VFS path (``seekvfs://…``) to a local ``Path``."""
        return self._fs_root / path.removeprefix(_SCHEME)

    def _reconstruct(self, fp: Path) -> str:
        """Reconstruct the VFS path from a local filesystem ``Path``."""
        return _SCHEME + str(fp.relative_to(self._fs_root))

    # ---------- pending thread bookkeeping ----------

    def _register(self, path: str, thread: threading.Thread) -> None:
        with self._pending_lock:
            self._pending[path] = thread

    def _cancel_pending(self, path: str) -> None:
        """Mark the pending thread for *path* as superseded.

        Threads cannot be cancelled, but we remove the reference so
        ``close()`` won't wait on a thread that has been superseded.
        The thread itself will detect the content mismatch and exit early.
        """
        with self._pending_lock:
            self._pending.pop(path, None)

    # ---------- derivative generation ----------

    def _generate_derivatives(
        self, content: bytes | str
    ) -> tuple[str, str, list[float]]:
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        n = len(text)

        l0 = text if n <= self._l0_threshold else self._summarizer.abstract(content)
        l1 = text if n <= self._l1_threshold else self._summarizer.overview(content)

        emb = self._embedder.embed(l0)
        return l0, l1, emb

    def _background_body(self, path: str, raw: bytes) -> None:
        try:
            l0, l1, emb = self._generate_derivatives(raw)
        except Exception:
            logger.exception("background derivative generation failed for path=%r", path)
            return

        fp = self._local(path)
        try:
            current = fp.read_bytes()
        except OSError:
            return
        if current != raw:
            return

        try:
            self._dao.update_derivatives(path, l0, l1, emb)
        except Exception:
            logger.exception("background DB write failed for path=%r", path)

        with self._pending_lock:
            if self._pending.get(path) is threading.current_thread():
                self._pending.pop(path, None)

    def _schedule_background(self, path: str, raw: bytes) -> threading.Thread:
        self._cancel_pending(path)
        thread = threading.Thread(
            target=self._background_body,
            args=(path, raw),
            daemon=True,
        )
        self._register(path, thread)
        thread.start()
        return thread

    # ---------- BackendProtocol ----------

    def write(self, path: str, content: bytes | str) -> None:
        self._ensure_ready()
        raw = _to_bytes(content)

        fp = self._local(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(raw)

        self._dao.upsert_init(path)

        if self._generation == "sync":
            l0, l1, emb = self._generate_derivatives(content)
            self._dao.update_derivatives(path, l0, l1, emb)
        else:
            self._schedule_background(path, raw)

    def read(self, path: str, hint: str | None = None) -> FileData:
        self._ensure_ready()
        if hint == "l2":
            return self.read_full(path)

        if hint == "l0":
            exists, val = self._dao.get_l0(path)
            if not exists:
                raise NotFoundError(path)
            if val is None:
                raise TierNotAvailable(path)
            return FileData(val.encode("utf-8"), "utf-8")

        if hint == "l1":
            exists, val = self._dao.get_l1(path)
            if not exists:
                raise NotFoundError(path)
            if val is None:
                raise TierNotAvailable(path)
            return FileData(val.encode("utf-8"), "utf-8")

        if hint is not None:
            raise BackendError(
                f"unknown hint {hint!r};"
                " OceanbaseFsBackend accepts None / 'l0' / 'l1' / 'l2'"
            )

        exists, l1_val, l0_val = self._dao.get_l1_l0(path)
        if exists:
            if l1_val is not None:
                return FileData(l1_val.encode("utf-8"), "utf-8")
            if l0_val is not None:
                return FileData(l0_val.encode("utf-8"), "utf-8")

        fp = self._local(path)
        if not fp.exists():
            raise NotFoundError(path)
        return FileData(fp.read_bytes()[: self._fallback_l2_chars], "utf-8")

    def read_full(self, path: str) -> FileData:
        fp = self._local(path)
        if not fp.exists():
            raise NotFoundError(path)
        return FileData(fp.read_bytes(), "utf-8")

    def read_batch(self, paths: list[str]) -> dict[str, FileData]:
        return {p: self.read(p) for p in paths}

    def search(
        self,
        query: str,
        path_pattern: str | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> SearchResult:
        """Vector search via OceanBase; falls back to lexical if embedder fails."""
        self._ensure_ready()
        query_emb: list[float] | None = None
        try:
            query_emb = self._embedder.embed(query)
        except Exception:
            logger.exception(
                "embedder failed on query %r; falling back to lexical search", query
            )

        hits: list[SearchHit] = []
        searched: list[str] = []

        if query_emb is not None:
            path_like = (
                path_pattern.replace("*", "%").replace("?", "_")
                if path_pattern
                else None
            )
            rows = self._dao.vector_search(query_emb, path_like, score_threshold, limit)
            for path, snippet, score in rows:
                searched.append(path)
                hits.append(SearchHit(path=path, snippet=snippet or "", score=score))
        else:
            q_low = query.lower()
            for fp in self._fs_root.rglob("*"):
                if not fp.is_file():
                    continue
                vfs_path = self._reconstruct(fp)
                if path_pattern and not fnmatch.fnmatch(vfs_path, path_pattern):
                    continue
                try:
                    data = fp.read_bytes()
                except OSError:
                    continue
                searched.append(vfs_path)
                text_content = data.decode("utf-8", errors="replace")
                score = 1.0 if q_low and q_low in text_content.lower() else 0.0
                if score_threshold is not None and score < score_threshold:
                    continue
                if score <= 0:
                    continue
                hits.append(SearchHit(path=vfs_path, snippet="", score=score))

        return SearchResult(query=query, hits=hits[:limit], searched_paths=searched)

    def ls(
        self,
        path: str,
        pattern: str | None = None,
        recursive: bool = False,
    ) -> list[FileInfo]:
        self._ensure_ready()
        prefix = path if path.endswith("/") else path + "/"
        local_rel = prefix.removeprefix(_SCHEME).rstrip("/")
        local_dir = self._fs_root / local_rel if local_rel else self._fs_root

        out: list[tuple[str, int, datetime]] = []
        if local_dir.exists():
            candidates = local_dir.rglob("*") if recursive else local_dir.iterdir()
            for fp in candidates:
                if not fp.is_file():
                    continue
                rest = str(fp.relative_to(local_dir))
                if pattern is not None and not fnmatch.fnmatch(rest, pattern):
                    continue
                stat = fp.stat()
                out.append(
                    (
                        prefix + rest,
                        stat.st_size,
                        datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )

        if not out:
            return []

        snippets = self._dao.batch_l0([t[0] for t in out])
        result = [
            FileInfo(
                path=p,
                size=sz,
                mtime=mt,
                is_dir=False,
                snippet=snippets.get(p),
            )
            for p, sz, mt in out
        ]
        result.sort(key=lambda fi: fi.path)
        return result

    def edit(self, path: str, old: str, new: str) -> int:
        fp = self._local(path)
        with self._edit_lock:
            if not fp.exists():
                raise NotFoundError(path)
            text_content = fp.read_bytes().decode("utf-8", errors="replace")
            count = text_content.count(old)
            if count == 0:
                return 0
            new_raw = text_content.replace(old, new).encode("utf-8")
            fp.write_bytes(new_raw)

        self._dao.clear_derivatives(path)

        if self._generation == "sync":
            l0, l1, emb = self._generate_derivatives(new_raw)
            self._dao.update_derivatives(path, l0, l1, emb)
        else:
            self._schedule_background(path, new_raw)

        return count

    def grep(
        self,
        pattern: str,
        path_pattern: str | None = None,
    ) -> list[GrepMatch]:
        self._ensure_ready()
        out: list[GrepMatch] = []
        for fp in self._fs_root.rglob("*"):
            if not fp.is_file():
                continue
            vfs_path = self._reconstruct(fp)
            if path_pattern and not fnmatch.fnmatch(vfs_path, path_pattern):
                continue
            try:
                text_content = fp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for idx, line in enumerate(text_content.splitlines(), start=1):
                if pattern in line:
                    out.append(GrepMatch(path=vfs_path, line_number=idx, line=line))
        return out

    def delete(self, path: str) -> None:
        self._ensure_ready()
        self._cancel_pending(path)

        fp = self._local(path)
        if not fp.exists():
            raise NotFoundError(path)
        fp.unlink()
        parent = fp.parent
        while parent != self._fs_root:
            try:
                parent.rmdir()
                parent = parent.parent
            except OSError:
                break

        self._dao.delete(path)

    def close(self) -> None:
        """Wait for all in-flight background derivative generation threads."""
        with self._pending_lock:
            pending = list(self._pending.values())
        for thread in pending:
            thread.join()


__all__ = ["OceanbaseFsBackend", "GenerationMode"]
