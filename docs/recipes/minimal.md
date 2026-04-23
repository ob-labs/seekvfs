# Minimal recipe

The simplest persistent recipe: one file per VFS path stored under a local directory tree. No summaries, no embeddings — just the simplest thing that satisfies `seekvfs.BackendProtocol` and survives process restarts.

**This is a recipe, not the protocol.** Lives under `seekvfs_recipes.minimal` so that `src/seekvfs/` stays free of concrete storage implementations.

If you need vector search or tiered reads, use the [Maximal recipe](maximal.md) instead.

## When to use it

- Single-process agents that need durable storage (data survives restarts)
- Local-file workloads: notes, session memories, document stores
- As a stepping stone before wiring up a database backend
- Any case where summaries / embeddings are overkill, but in-memory loss is unacceptable

## When NOT to use it

- Multi-process or multi-host deployments (local files are not shared)
- High-throughput concurrent writes (single `edit` lock; `write` is last-write-wins)
- Retrieval by meaning rather than exact substring — use the [Maximal recipe](maximal.md)

## Quickstart

```python
from seekvfs import VFS
from seekvfs_recipes.minimal import FileBackend

vfs = VFS(routes={
    "seekvfs://notes/": {"backend": FileBackend("/data/agent_notes")},
})

vfs.write("seekvfs://notes/hello.md", "hello world")

fd = vfs.read("seekvfs://notes/hello.md")
print(fd.content)   # b'hello world'

for info in vfs.ls("seekvfs://notes/"):
    print(info.path, info.size)

for m in vfs.grep("hello"):
    print(m.path, m.line_number, m.line)
```

`read(path)` and `read_full(path)` return the same content — this backend stores only one representation per path. `hint` values are accepted but ignored.

`search(query)` performs a literal substring match across file contents and returns hits with score `1.0` for a match. It is deliberately minimal: for semantic / vector search, use the Maximal recipe.

## Path mapping

Every VFS path maps to a local file by stripping the `seekvfs://` scheme (if present) and appending to `root_dir`:

| VFS path | Local file |
|---|---|
| `seekvfs://notes/hello.md` | `{root_dir}/notes/hello.md` |
| `seekvfs://notes/sub/foo.md` | `{root_dir}/notes/sub/foo.md` |

Intermediate directories are created automatically on `write`. Empty directories are removed automatically on `delete`.

## Adapt to your own storage

The whole backend is ~200 lines in [`src/seekvfs_recipes/minimal/backend.py`](../../src/seekvfs_recipes/minimal/backend.py). To switch to a different storage medium (object store, NFS, S3-compatible API):

1. Copy the file into your project.
2. Replace `fp.write_bytes(data)` (and the corresponding `fp.read_bytes()` / `fp.read_text()` calls) with your storage client calls.
3. Keep the same method signatures so it still satisfies `BackendProtocol`.

If along the way you decide you want summaries or vector search, switch to the [Maximal recipe](maximal.md) as your starting point instead.
