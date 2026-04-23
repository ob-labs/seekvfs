# seekvfs

[English](README.md) | 简体中文

seekvfs 是一个面向 AI Agent 的虚拟文件系统接口，允许你为不同的存储后端分配不同的 URI 前缀，再以一套统一的文件接口暴露给 agent。核心包只负责 URI 归一化、按前缀路由请求、合并跨后端搜索结果，以及导出 agent 工具。底层的实现细节，如何存储、索引、摘要或 embedding，都由 backend 自己决定。

## 安装

要求 Python 3.11+。

```bash
pip install seekvfs
```

如果需要完整内置集成：

```bash
pip install "seekvfs[full]"
```

## 快速开始

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

路由前缀也可以写成 `notes/` 这种裸路径，SeekVFS 会自动归一化为 `seekvfs://notes/`。

更多示例见：[docs/quickstart.md](docs/quickstart.md)

## Tools

`vfs.tools` 会返回一套中立的 8 个 agent 工具规范：`search`、`read`、`read_full`、`write`、`edit`、`ls`、`grep` 和 `delete`，你可以将其导出给不同的 Agent：比如 OpenAI、Anthropic、LangGraph 和 MCP 等。

## Recipes

| Recipe | 适合场景 | 存储形态 | 文档 |
|---|---|---|---|
| `seekvfs_recipes.minimal` | 需要一个最小可持久化 backend | 每个路径对应本地磁盘上的一个文件 | [docs/recipes/minimal.md](docs/recipes/minimal.md) |
| `seekvfs_recipes.maximal` | 需要分层读取和语义搜索 | L2 在文件系统，L0/L1 与 embedding 在 OceanBase | [docs/recipes/maximal.md](docs/recipes/maximal.md) |

同一个 `VFS` 里也可以混用不同 recipe，只要把它们挂到不同 URI 前缀下即可。

## 文档

- Quickstart: [docs/quickstart.md](docs/quickstart.md)
- Minimal recipe: [docs/recipes/minimal.md](docs/recipes/minimal.md)
- Maximal recipe: [docs/recipes/maximal.md](docs/recipes/maximal.md)

## 许可证

[Apache 2.0](LICENSE)。
