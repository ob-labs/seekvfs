"""VfsStorageDAO — database access layer for OceanbaseFsBackend.

All SQL lives here. To adapt the Maximal recipe to a different schema,
table name, column names, or database engine, subclass ``VfsStorageDAO`` and
override only the methods you need, then pass your DAO to the backend::

    class MyDAO(VfsStorageDAO):
        \"\"\"Custom schema: renamed columns, extra business fields.\"\"\"

        def upsert_init(self, path: str) -> None:
            with self._client.engine.connect() as conn:
                conn.execute(
                    text(
                        \"INSERT INTO my_docs (uri, summary, overview, vec)\"
                        \" VALUES (:path, NULL, NULL, NULL)\"
                        \" ON DUPLICATE KEY UPDATE\"
                        \"   summary = NULL, overview = NULL, vec = NULL\"
                    ),
                    {\"path\": path},
                )
                conn.commit()

        def update_derivatives(
            self, path: str, l0: str, l1: str, emb: list[float]
        ) -> None:
            with self._client.engine.connect() as conn:
                conn.execute(
                    text(
                        \"UPDATE my_docs\"
                        \" SET summary = :l0, overview = :l1, vec = :emb\"
                        \" WHERE uri = :path\"
                    ),
                    {\"l0\": l0, \"l1\": l1, \"emb\": _vec_to_str(emb), \"path\": path},
                )
                conn.commit()

        # ... override other methods as needed ...


    backend = OceanbaseFsBackend(
        ob_client=client,
        fs_root=\"/data/agent_files\",
        summarizer=...,
        embedder=...,
        dao=MyDAO(client),   # ← inject your custom DAO
    )

Default schema (executed by :meth:`VfsStorageDAO.initialize`)::

    CREATE TABLE IF NOT EXISTS vfs_storage (
        path        VARCHAR(512)    NOT NULL,
        l0          TEXT            DEFAULT NULL,   -- short abstract (~100 tokens)
        l1          MEDIUMTEXT      DEFAULT NULL,   -- overview (~2 k tokens)
        embedding   VECTOR(1536)    DEFAULT NULL,   -- L0 embedding; adjust dim below
        updated_at  TIMESTAMP       NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (path),
        VECTOR INDEX idx_emb (embedding)
            WITH (distance = L2, type = HNSW, lib = vsag)
    );

**To customise the schema**, override :meth:`VfsStorageDAO.initialize` in a subclass.
Common tweaks:

* **Change vector dimension** — pass ``vector_dim=3072`` to the constructor; no subclass needed.
* **Rename table** — pass ``table="my_table"`` to the constructor; no subclass needed.
* **Rename columns / add columns** — subclass ``VfsStorageDAO``, override ``initialize()``
  *and* every SQL method that references those columns (``upsert_init``,
  ``update_derivatives``, ``get_l0``, ``get_l1``, ``get_l1_l0``,
  ``clear_derivatives``, ``vector_search``, ``batch_l0``, ``find_incomplete``).
* **Different DB engine** — subclass and rewrite all methods; keep the same return types.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _vec_to_str(vec: list[float]) -> str:
    """Encode a float list to OceanBase ``VECTOR`` literal ``'[x,y,...]'``."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


class VfsStorageDAO:
    """Default OceanBase data access layer for the Maximal recipe.

    Every public method corresponds to exactly one logical database
    operation.  Subclass and override any method to adapt the schema or
    SQL dialect without touching the backend orchestration logic.

    Args:
        client: A ``pyobvector.ObVecClient`` instance connected to OceanBase.
        table: Table name (default ``"vfs_storage"``).
        vector_dim: Dimension of the embedding vector column (default 1536).
            Must match the output dimension of your :class:`Embedder`.
            Common values: OpenAI text-embedding-3-small → 1536,
            text-embedding-v3 (Qwen) → 1024.
    """

    def __init__(
        self, client: Any, table: str = "vfs_storage", vector_dim: int = 1536
    ) -> None:
        self._client = client
        self._table = table
        self._vector_dim = vector_dim

    def initialize(self) -> None:
        """Create the table and vector index if they do not already exist.

        Safe to call multiple times — uses ``CREATE TABLE IF NOT EXISTS``.
        Called automatically by :class:`OceanbaseFsBackend` on first use,
        so you rarely need to invoke this directly.

        To change the schema, subclass :class:`VfsStorageDAO` and override
        this method.  See the module docstring for a full customisation guide.
        """
        ddl = (
            f"CREATE TABLE IF NOT EXISTS {self._table} ("
            f"  path        VARCHAR(512)  NOT NULL,"
            f"  l0          TEXT          DEFAULT NULL,"
            f"  l1          MEDIUMTEXT    DEFAULT NULL,"
            f"  embedding   VECTOR({self._vector_dim}) DEFAULT NULL,"
            f"  updated_at  TIMESTAMP     NOT NULL"
            f"              DEFAULT CURRENT_TIMESTAMP"
            f"              ON UPDATE CURRENT_TIMESTAMP,"
            f"  PRIMARY KEY (path),"
            f"  VECTOR INDEX idx_emb (embedding)"
            f"    WITH (distance = L2, type = HNSW, lib = vsag)"
            f")"
        )
        with self._client.engine.connect() as conn:
            conn.execute(text(ddl))
            conn.commit()
        logger.info("VfsStorageDAO.initialize: table %r ready (dim=%d)", self._table, self._vector_dim)

    # ------------------------------------------------------------------ #
    # Write-path                                                           #
    # ------------------------------------------------------------------ #

    def upsert_init(self, path: str) -> None:
        """Ensure a row for *path* exists; reset stale derivatives to NULL.

        Called by ``write()`` before scheduling derivative generation.

        Uses ``REPLACE INTO`` (DELETE + INSERT) instead of
        ``ON DUPLICATE KEY UPDATE`` to avoid OceanBase HNSW vector-index
        conflicts when overwriting an existing embedding column.
        """
        with self._client.engine.connect() as conn:
            conn.execute(
                text(
                    f"REPLACE INTO {self._table} (path, l0, l1, embedding)"
                    f" VALUES (:path, NULL, NULL, NULL)"
                ),
                {"path": path},
            )
            conn.commit()

    def update_derivatives(
        self, path: str, l0: str, l1: str, emb: list[float]
    ) -> None:
        """Write generated L0/L1/embedding for *path*.

        Called after derivative generation completes.
        """
        with self._client.engine.connect() as conn:
            conn.execute(
                text(
                    f"UPDATE {self._table}"
                    f" SET l0 = :l0, l1 = :l1, embedding = :emb"
                    f" WHERE path = :path"
                ),
                {"l0": l0, "l1": l1, "emb": _vec_to_str(emb), "path": path},
            )
            conn.commit()

    def clear_derivatives(self, path: str) -> None:
        """Set L0/L1/embedding back to NULL after an ``edit()``.

        Marks the stored derivatives as stale; a new generation pass
        will fill them in.
        """
        with self._client.engine.connect() as conn:
            conn.execute(
                text(
                    f"UPDATE {self._table}"
                    f" SET l0 = NULL, l1 = NULL, embedding = NULL"
                    f" WHERE path = :path"
                ),
                {"path": path},
            )
            conn.commit()

    def delete(self, path: str) -> None:
        """Remove the row for *path* from the database."""
        with self._client.engine.connect() as conn:
            conn.execute(
                text(f"DELETE FROM {self._table} WHERE path = :path"),
                {"path": path},
            )
            conn.commit()

    # ------------------------------------------------------------------ #
    # Read-path                                                            #
    # ------------------------------------------------------------------ #

    def get_l0(self, path: str) -> tuple[bool, str | None]:
        """Fetch the L0 abstract for *path*.

        Returns:
            ``(row_exists, l0_value)``

            - ``row_exists = False`` → no DB record (path was never written).
            - ``row_exists = True, l0_value = None`` → row exists but L0 not yet generated.
            - ``row_exists = True, l0_value = "..."`` → L0 is available.
        """
        with self._client.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT l0 FROM {self._table} WHERE path = :path"),
                {"path": path},
            ).fetchone()
        if row is None:
            return False, None
        return True, row[0]

    def get_l1(self, path: str) -> tuple[bool, str | None]:
        """Fetch the L1 overview for *path*.  Same semantics as ``get_l0``."""
        with self._client.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT l1 FROM {self._table} WHERE path = :path"),
                {"path": path},
            ).fetchone()
        if row is None:
            return False, None
        return True, row[0]

    def get_l1_l0(
        self, path: str
    ) -> tuple[bool, str | None, str | None]:
        """Fetch L1 and L0 together (used for ``hint=None`` waterfall).

        Returns:
            ``(row_exists, l1_value, l0_value)``
        """
        with self._client.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT l1, l0 FROM {self._table} WHERE path = :path"),
                {"path": path},
            ).fetchone()
        if row is None:
            return False, None, None
        return True, row[0], row[1]

    # ------------------------------------------------------------------ #
    # Search                                                               #
    # ------------------------------------------------------------------ #

    def vector_search(
        self,
        emb: list[float],
        path_like: str | None,
        score_threshold: float | None,
        limit: int,
    ) -> list[tuple[str, str | None, float]]:
        """Run vector similarity search.

        Args:
            emb: Query embedding (dense float vector).
            path_like: Optional SQL ``LIKE`` pattern to restrict paths.
            score_threshold: Minimum score (``HAVING score >= threshold``).
            limit: Maximum number of hits to return.

        Returns:
            List of ``(path, l0_snippet, score)`` ordered by score DESC.
            ``l0_snippet`` may be ``None`` if L0 is not yet generated.
        """
        params: dict[str, Any] = {"emb": _vec_to_str(emb), "limit": limit}

        where_parts = ["embedding IS NOT NULL"]
        if path_like:
            where_parts.append("path LIKE :path_like")
            params["path_like"] = path_like

        sql = (
            f"SELECT path, l0, 1 - l2_distance(embedding, :emb) AS score"
            f" FROM {self._table}"
            f" WHERE {' AND '.join(where_parts)}"
        )
        if score_threshold is not None:
            sql += " HAVING score >= :score_threshold"
            params["score_threshold"] = score_threshold
        sql += " ORDER BY score DESC LIMIT :limit"

        with self._client.engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()

        return [(r[0], r[1], float(r[2])) for r in rows]

    # ------------------------------------------------------------------ #
    # Bulk / utility                                                       #
    # ------------------------------------------------------------------ #

    def batch_l0(self, paths: list[str]) -> dict[str, str | None]:
        """Fetch L0 snippets for multiple *paths* in one query.

        Returns a mapping ``{path: l0_or_None}``; paths with no DB row
        are absent from the result.
        """
        if not paths:
            return {}
        placeholders = ", ".join([f":p{i}" for i in range(len(paths))])
        params = {f"p{i}": p for i, p in enumerate(paths)}
        with self._client.engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT path, l0 FROM {self._table}"
                    f" WHERE path IN ({placeholders})"
                ),
                params,
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def find_incomplete(
        self, all_paths: list[str]
    ) -> tuple[set[str], set[str]]:
        """Identify paths that need derivative generation.

        Used by ``reconcile()`` to find what needs repair.

        Returns:
            ``(missing_derivatives, no_db_record)``

            - ``missing_derivatives``: paths that have a DB row but at
              least one of l0/l1/embedding is NULL.
            - ``no_db_record``: FS files that have no DB row at all.
        """
        if not all_paths:
            return set(), set()

        placeholders = ", ".join([f":p{i}" for i in range(len(all_paths))])
        params = {f"p{i}": p for i, p in enumerate(all_paths)}

        with self._client.engine.connect() as conn:
            missing_deriv: set[str] = {
                r[0]
                for r in conn.execute(
                    text(
                        f"SELECT path FROM {self._table}"
                        f" WHERE path IN ({placeholders})"
                        f" AND (l0 IS NULL OR l1 IS NULL OR embedding IS NULL)"
                    ),
                    params,
                ).fetchall()
            }
            in_db: set[str] = {
                r[0]
                for r in conn.execute(
                    text(
                        f"SELECT path FROM {self._table}"
                        f" WHERE path IN ({placeholders})"
                    ),
                    params,
                ).fetchall()
            }

        no_db_record = set(all_paths) - in_db
        return missing_deriv, no_db_record


__all__ = ["VfsStorageDAO"]
