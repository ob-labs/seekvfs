# seekvfs

English | [简体中文](README.zh-CN.md)

A **protocol-level** unified VFS for AI agents. Bind any URI prefix to any storage backend; get agent-ready tool specs for free.

`seekvfs` is a thin contract, not a business framework, and not a storage engine. It defines how agents talk to storage — what shape to give the data (single blob, tiered summaries, embeddings, etc.) is up to the backend. Two built-in recipes ship alongside the core: **Minimal** (file-based, zero database) and **Maximal** (filesystem + OceanBase + vector search, the best-combination backend).

## Why

Agents need one mental model for "files": one URI scheme, one tool surface, one way to read / write / search. Underneath, different classes of data need different storage (in-memory, filesystem, Postgres, object store, vector DB). This library gives you the facade and the routing; you plug in the backend.

## Install

```bash
# Minimal — core only, no database required
pip install seekvfs

# Full — Maximal recipe + all LangChain providers + all integrations
pip install "seekvfs[full]"
```

## Pick a recipe

| Recipe | Use when | Docs |
|---|---|---|
| [`seekvfs_recipes.minimal`](docs/recipes/minimal.md) | **Minimal** — durable single-process storage, no database needed | [minimal.md](docs/recipes/minimal.md) |
| [`seekvfs_recipes.maximal`](docs/recipes/maximal.md) | **Maximal** — best-combination: FS + OceanBase + vector search | [maximal.md](docs/recipes/maximal.md) |

Recipes are NOT part of the protocol — they live under `seekvfs_recipes.*` so the `seekvfs` core package stays free of concrete backends.

## 30-second quickstart

```python
from seekvfs import VFS
from seekvfs_recipes.minimal import FileBackend

vfs = VFS(routes={
    "seekvfs://notes/": {"backend": FileBackend("/data/agent_notes")},
})
vfs.write("seekvfs://notes/hello.md", "hello world")
fd = vfs.read("seekvfs://notes/hello.md")
print(fd.content)   # b'hello world'
```

> Prefix names are yours to choose — the protocol does not recommend any naming convention.

Full walkthrough in [`docs/quickstart.md`](docs/quickstart.md).

## Design

See [`DESIGN_NEW_VFS.md`](DESIGN_NEW_VFS.md) for the full protocol. TL;DR:

- **URI:** `seekvfs://{path}`. Case-preserving. Trailing `/` = directory.
- **Routes:** longest-prefix match from `{prefix: RouteConfig}`. `RouteConfig` only requires `backend`.
- **Protocol contract:** content written via `write` must be retrievable via `read_full`. Everything else — tiers, embeddings, summaries, generation lifecycle — is backend-defined.
- **Tools:** `vfs.tools` returns a neutral `ToolSpecSet` exportable to OpenAI / Anthropic / LangGraph / MCP.

## License

Apache 2.0. See [`LICENSE`](LICENSE).
