# seekvfs

[English](README.md) | 简体中文

面向 AI Agent 的**协议层**统一 VFS。任意 URI 前缀绑任意存储后端,开箱即得可直接给 agent 使用的工具定义。

`seekvfs` 是一份**轻薄契约**,不是业务框架,也不是存储引擎。它只规定 agent 如何和存储对话 —— 数据存成什么形状(单块 blob、分层摘要、向量等)由 backend 自己决定。两个内置 recipe 覆盖常见场景:**Minimal**（文件直存,零依赖）和 **Maximal**（文件系统 + OceanBase + 向量检索,最佳搭配组合）。

## 为什么要做这个

Agent 需要一套统一的"文件"心智模型:一个 URI scheme、一套工具接口、统一的 read / write / search 动作。而底层不同类型的数据需要不同的存储介质(内存、文件系统、Postgres、对象存储、向量库)。本库只提供门面和路由,你把后端插进来就行。

## 安装

```bash
# 最小安装 —— 仅核心，无需数据库
pip install seekvfs

# 全量安装 —— Maximal recipe + 全部 LangChain provider + 全部集成
pip install "seekvfs[full]"
```

## 挑一个 recipe

| Recipe | 什么时候用 | 文档 |
|---|---|---|
| [`seekvfs_recipes.minimal`](docs/recipes/minimal.md) | **Minimal** — 单进程持久化存储,无需数据库,重启不丢数据 | [minimal.md](docs/recipes/minimal.md) |
| [`seekvfs_recipes.maximal`](docs/recipes/maximal.md) | **Maximal** — 最佳搭配组合:FS + OceanBase + 向量搜索 | [maximal.md](docs/recipes/maximal.md) |

Recipe **不属于协议**,放在 `seekvfs_recipes.*` 下,和 `seekvfs` 核心严格分离。

## 30 秒快速上手

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

> 前缀命名由你决定 —— 协议不给出任何命名建议。

完整教程见 [`docs/quickstart.md`](docs/quickstart.md)。

## 设计

- **URI:** `seekvfs://{path}`,区分大小写,尾斜杠表示目录
- **路由:** 从 `{前缀: RouteConfig}` 中按最长前缀匹配。`RouteConfig` 只要 `backend` 一个字段
- **协议承诺:** 通过 `write` 写进去的 content 必须能从 `read_full` 原样取出。其它(分层、embedding、摘要、生成时机)全部由 backend 自定
- **工具:** `vfs.tools` 返回中立的 `ToolSpecSet`,可导出到 OpenAI / Anthropic / LangGraph / MCP

## 协议 vs Recipe vs 业务

| ✅ 协议层 | ⚙ Recipe 层(官方最佳实践) | ❌ 业务层(留给你) |
|---|---|---|
| `VFS` 门面 + `BackendProtocol` | `OceanbaseFsBackend` 三层 + 向量检索 | 具体对接某 DB 的细节 |
| `seekvfs://` URI 模型 | `Summarizer / Embedder` 协议 | URI 路径的业务含义 |
| 路径前缀路由机制 | `hint="l0"/"l1"/"l2"` 值域 | 具体摘要 prompt / 模型 |
| 工具 `ToolSpec` + 适配器 | `reconcile` 补缺作业 | 路径命名规范 |

一句话:**协议给能力;recipe 给推荐做法;业务给决定。**

## 许可

Apache 2.0,详见 [`LICENSE`](LICENSE)。
