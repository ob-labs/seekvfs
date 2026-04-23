# Maximal recipe

Production-grade best-combination backend: **L2 full content on local filesystem**, **L0/L1/embedding in OceanBase**. Agents get "read short first, read full on demand" UX and vector search out of the box.

| Tier | Content | Storage |
|---|---|---|
| **L0** | Short abstract (~100 tokens) | OceanBase — basis for vector search |
| **L1** | Structured overview (~2k tokens) | OceanBase — returned by default `read()` |
| **L2** | Full original content | Local filesystem — returned by `read_full()` |
| **embedding** | Dense vector over L0 | OceanBase VECTOR column |

**This is a recipe, not the protocol.** The core `seekvfs` protocol does not know about tiers; they live entirely inside `OceanbaseFsBackend`.

If you don't need summaries or vector search, start with the simpler [Minimal recipe](minimal.md).

## Prerequisites

- OceanBase 4.x with vector support:
  ```sql
  SET GLOBAL observer_vector_index_enabled = ON;
  ```
- Python dependencies:
  ```bash
  pip install asyncmy
  pip install "seekvfs[anthropic]"   # ClaudeSummarizer
  pip install "seekvfs[openai]"      # OpenAIEmbedder
  ```

## Step 1 — Create the OceanBase schema

The table is created automatically when the backend first runs (`VfsStorageDAO.initialize()`
is called on first use, so you don't need to run any SQL manually).

The DDL and customisation options are documented in
[`src/seekvfs_recipes/maximal/dao.py`](../../src/seekvfs_recipes/maximal/dao.py).
Common tweaks:

- **Different vector dimension** — pass `vector_dim=3072` to `VfsStorageDAO(...)`.
- **Different table name** — pass `table="my_table"` to `VfsStorageDAO(...)`.
- **Custom columns / DB engine** — subclass `VfsStorageDAO` and override `initialize()`
  plus every SQL method that references the changed columns.

## Step 2 — Build the backend

```python
import asyncio
import asyncmy
from seekvfs import VFS
from seekvfs_recipes.maximal import (
    OceanbaseFsBackend,
    ClaudeSummarizer,
    OpenAIEmbedder,
)

async def build_vfs() -> VFS:
    pool = await asyncmy.create_pool(
        host="obproxy.local", port=2883,
        user="kb", password="***", db="agent_kb",
        minsize=2, maxsize=10,
    )

    backend = OceanbaseFsBackend(
        ob_pool=pool,
        fs_root="/data/agent_files",
        summarizer=ClaudeSummarizer(
            model="claude-opus-4-7",
            abstract_prompt="Summarize in ~100 tokens. Output only the summary.",
            overview_prompt="Produce a ~2000 token structured overview.",
        ),
        embedder=OpenAIEmbedder(model="text-embedding-3-small"),  # dim=1536
        generation="async",   # write returns immediately; derivatives generated in background
    )

    return VFS(routes={"seekvfs://notes/": {"backend": backend}})
```

## Step 3 — Use it

```python
async def main():
    vfs = await build_vfs()

    # Write — L2 persisted to disk immediately; L0/L1/embedding generated async
    await vfs.write("seekvfs://notes/python_pref.md",
                    "The user strongly prefers Python for backend work.")

    # Default read — returns L1 overview (or L0/truncated-L2 if not yet generated)
    fd = await vfs.read("seekvfs://notes/python_pref.md")
    print(fd.content.decode())

    # Explicit hint — strict L0 abstract; raises TierNotAvailable if not ready yet
    fd = await vfs.read("seekvfs://notes/python_pref.md", hint="l0")

    # Full content — always the original L2
    fd = await vfs.read_full("seekvfs://notes/python_pref.md")

    # Vector search — embedding-based; snippet = L0 abstract
    result = await vfs.search("programming language preference", limit=5)
    for hit in result.hits:
        print(f"{hit.score:.3f}  {hit.path}  {hit.snippet}")

    # Wait for any in-flight async derivative generation before shutdown
    await vfs.aclose()

asyncio.run(main())
```

## Hint values

`read(path, hint=...)` accepts:

| hint | behaviour |
|---|---|
| `None` | Waterfall: L1 → L0 → truncated L2 (first 8000 chars) |
| `"l0"` | Strict L0; raises `TierNotAvailable` if not yet generated |
| `"l1"` | Strict L1; raises `TierNotAvailable` if not yet generated |
| `"l2"` | Full content (equivalent to `read_full`) |
| anything else | `BackendError` |

Hint values are a recipe-level convention. The core protocol only passes them through verbatim.

## Reconcile

If async generation was interrupted (process crash, task cancellation, bulk-loaded content), run `reconcile` to backfill any missing L0/L1/embedding:

```python
from seekvfs_recipes.maximal import reconcile

stats = await reconcile(backend)
# {"checked": 120, "repaired": 4, "failed": 0}
```

Reconcile scans the filesystem, queries OceanBase for missing derivatives, and regenerates them. Safe to run at any time, including while the backend is live.

## Data flow — one write

```
vfs.write("seekvfs://notes/foo.md", "The user prefers Python.")
  │
  ├─ 1. Write L2 → /data/agent_files/notes/foo.md
  ├─ 2. OB INSERT (path, l0=NULL, l1=NULL, embedding=NULL)
  └─ 3. (async) Summarizer + Embedder:
           l0 = abstract(content)          → "User prefers Python for backend."
           l1 = overview(content)          → "The user stated a strong..."
           embedding = embed(l0)           → [0.12, ...]
           OB UPDATE SET l0, l1, embedding WHERE path = ...
```

## Customising the schema (VfsStorageDAO)

All SQL lives in [`seekvfs_recipes.maximal.VfsStorageDAO`](../../src/seekvfs_recipes/maximal/dao.py).
Subclass it, override the methods you need, and inject the result into the backend.
The orchestration logic (async derivative scheduling, file I/O, reconcile) stays untouched.

### Example — rename columns

```python
from seekvfs_recipes.maximal import OceanbaseFsBackend, VfsStorageDAO
from seekvfs_recipes.maximal.dao import _vec_to_str   # helper: list[float] → OB string


class MyDAO(VfsStorageDAO):
    """Custom schema: different table / column names."""

    async def upsert_init(self, path: str) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO my_docs (uri, summary, overview, vec)"
                    " VALUES (%s, NULL, NULL, NULL)"
                    " ON DUPLICATE KEY UPDATE"
                    "   summary = NULL, overview = NULL, vec = NULL",
                    (path,),
                )
                await conn.commit()

    async def update_derivatives(self, path, l0, l1, emb):
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE my_docs SET summary=%s, overview=%s, vec=%s WHERE uri=%s",
                    (l0, l1, _vec_to_str(emb), path),
                )
                await conn.commit()

    async def clear_derivatives(self, path):
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE my_docs SET summary=NULL, overview=NULL, vec=NULL WHERE uri=%s",
                    (path,),
                )
                await conn.commit()

    async def delete(self, path):
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM my_docs WHERE uri=%s", (path,))
                await conn.commit()

    async def get_l0(self, path):
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT summary FROM my_docs WHERE uri=%s", (path,))
                row = await cur.fetchone()
        return (False, None) if row is None else (True, row[0])

    async def get_l1(self, path):
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT overview FROM my_docs WHERE uri=%s", (path,))
                row = await cur.fetchone()
        return (False, None) if row is None else (True, row[0])

    async def get_l1_l0(self, path):
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT overview, summary FROM my_docs WHERE uri=%s", (path,)
                )
                row = await cur.fetchone()
        return (False, None, None) if row is None else (True, row[0], row[1])

    async def vector_search(self, emb, path_like, score_threshold, limit):
        emb_str = _vec_to_str(emb)
        sql = (
            "SELECT uri, summary, 1 - l2_distance(vec, %s) AS score"
            " FROM my_docs WHERE vec IS NOT NULL"
        )
        params = [emb_str]
        if path_like:
            sql += " AND uri LIKE %s"
            params.append(path_like)
        if score_threshold is not None:
            sql += " HAVING score >= %s"
            params.append(score_threshold)
        sql += " ORDER BY score DESC LIMIT %s"
        params.append(limit)
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return [(r[0], r[1], float(r[2])) for r in await cur.fetchall()]

    async def batch_l0(self, paths):
        if not paths:
            return {}
        ph = ", ".join(["%s"] * len(paths))
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT uri, summary FROM my_docs WHERE uri IN ({ph})", paths
                )
                return {r[0]: r[1] for r in await cur.fetchall()}

    async def find_incomplete(self, all_paths):
        if not all_paths:
            return set(), set()
        ph = ", ".join(["%s"] * len(all_paths))
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT uri FROM my_docs WHERE uri IN ({ph})"
                    f" AND (summary IS NULL OR overview IS NULL OR vec IS NULL)",
                    all_paths,
                )
                missing = {r[0] for r in await cur.fetchall()}
                await cur.execute(
                    f"SELECT uri FROM my_docs WHERE uri IN ({ph})", all_paths
                )
                in_db = {r[0] for r in await cur.fetchall()}
        return missing, set(all_paths) - in_db


backend = OceanbaseFsBackend(
    ob_pool=pool,
    fs_root="/data/agent_files",
    summarizer=...,
    embedder=...,
    dao=MyDAO(pool),   # ← inject custom DAO; table= param is ignored
)
```

### DAO method reference

| Method | Called by | Purpose |
|---|---|---|
| `upsert_init(path)` | `write()` | INSERT row; clear stale NULL on conflict |
| `update_derivatives(path, l0, l1, emb)` | `write()` / `edit()` / reconcile | Store generated tiers |
| `clear_derivatives(path)` | `edit()` | Set l0/l1/embedding back to NULL |
| `delete(path)` | `delete()` | Remove row |
| `get_l0(path) → (exists, val)` | `read(hint="l0")` | Fetch L0 |
| `get_l1(path) → (exists, val)` | `read(hint="l1")` | Fetch L1 |
| `get_l1_l0(path) → (exists, l1, l0)` | `read(hint=None)` | Waterfall fetch |
| `vector_search(emb, ...) → [(path, snippet, score)]` | `search()` | ANN search |
| `batch_l0(paths) → {path: l0}` | `ls()` | Enrich file listing with snippets |
| `find_incomplete(paths) → (missing_deriv, no_record)` | `reconcile()` | Find repair targets |

### Swapping the database engine

The same pattern works for Postgres + pgvector, SQLite-vec, or any other store — just override the SQL methods in your DAO subclass to use your driver's API.
