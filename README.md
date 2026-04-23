# seekvfs

English | [简体中文](README.zh-CN.md)

seekvfs is a virtual file system interface for AI agents. It lets you assign different URI prefixes to different storage backends and expose them through a single file interface. The core package only handles URI normalization, prefix-based routing, cross-backend search merging, and agent tool export. Storage layout, indexing, summaries, embeddings, and other implementation details are left to the backend.

## Install

Requires Python 3.11+.

```bash
pip install seekvfs
```

For the full built-in integrations:

```bash
pip install "seekvfs[full]"
```

## Quickstart

```python
from seekvfs import VFS
from seekvfs_recipes.minimal import FileBackend

vfs = VFS(
    routes={
        "seekvfs://notes/": {
            "backend": FileBackend("/data/agent_notes"),
        },
    }
)

vfs.write("seekvfs://notes/hello.md", "hello world")

fd = vfs.read("seekvfs://notes/hello.md")
print(fd.content.decode())

for item in vfs.ls("seekvfs://notes/"):
    print(item.path, item.size)
```

The route key can also be written as a bare prefix like `notes/`; SeekVFS will normalize it to `seekvfs://notes/`.

More examples: [docs/quickstart.md](docs/quickstart.md)

## Tools

`vfs.tools` returns a neutral set of 8 agent tool specs: `search`, `read`, `read_full`, `write`, `edit`, `ls`, `grep`, and `delete`. You can export them to different agent runtimes, including OpenAI, Anthropic, LangGraph, and MCP.

## Recipes

| Recipe | Use when | Storage shape | Docs |
|---|---|---|---|
| `seekvfs_recipes.minimal` | You want the smallest persistent backend | One file per path on local disk | [docs/recipes/minimal.md](docs/recipes/minimal.md) |
| `seekvfs_recipes.maximal` | You want tiered reads and semantic search | L2 on filesystem, L0/L1 + embeddings in OceanBase | [docs/recipes/maximal.md](docs/recipes/maximal.md) |

You can mix recipes in one `VFS` by mounting them on different URI prefixes.

## Documentation

- Quickstart: [docs/quickstart.md](docs/quickstart.md)
- Minimal recipe: [docs/recipes/minimal.md](docs/recipes/minimal.md)
- Maximal recipe: [docs/recipes/maximal.md](docs/recipes/maximal.md)

## License

[Apache 2.0](LICENSE).
