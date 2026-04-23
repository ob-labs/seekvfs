# Quickstart

This tutorial walks through a minimal `VFS` with the `minimal` recipe. For tiered reads + vector search, see [`recipes/maximal.md`](recipes/maximal.md).

## Install

```bash
pip install seekvfs
```

## Minimal VFS

```python
from seekvfs import VFS
from seekvfs_recipes.minimal import FileBackend

vfs = VFS(routes={
    "seekvfs://notes/": {"backend": FileBackend("/data/agent_notes")},
})

# Write — stored as a real file on disk
vfs.write("seekvfs://notes/hello.md", "hello world")

# Read — returns the stored content
fd = vfs.read("seekvfs://notes/hello.md")
print(fd.content.decode())
# hello world

# List
for info in vfs.ls("seekvfs://notes/"):
    print(info.path, info.size)

# Grep
for m in vfs.grep("hello"):
    print(m.path, m.line_number, m.line)
```

> Prefix names (`notes/`, `memories/`, `scratch/`, etc.) are entirely up to you. The protocol does not recommend or reserve any naming convention.

## Picking a recipe

Two built-in recipes are available at different complexity levels:

| Recipe | Use when | Details |
|---|---|---|
| `seekvfs_recipes.minimal` | **Minimal** — durable single-process storage without a database | [recipes/minimal.md](recipes/minimal.md) |
| `seekvfs_recipes.maximal` | **Maximal** — best-combination: FS + OceanBase + vector search | [recipes/maximal.md](recipes/maximal.md) |

Recipes are NOT part of the protocol. They're separate packages under `seekvfs_recipes.*` so `src/seekvfs/` stays free of concrete storage implementations.

## Mixing recipes in one VFS

Different URI prefixes can use different recipes — handy for separating "flat storage" from "tiered with search":

```python
from pyobvector import ObVecClient
from langchain_anthropic import ChatAnthropic
from langchain_openai import OpenAIEmbeddings

from seekvfs import VFS
from seekvfs_recipes.minimal import FileBackend
from seekvfs_recipes.maximal import (
    OceanbaseFsBackend,
    LangChainSummarizer,
    LangChainEmbedder,
)

ob_client = ObVecClient(uri="...", user="...", password="...", db_name="agent_kb")

vfs = VFS(routes={
    # Minimal: flat storage — files on disk, literal search only
    "seekvfs://docs/": {"backend": FileBackend("/data/agent_docs")},
    # Maximal: L2 on disk, L0/L1/embedding in OceanBase, vector search
    "seekvfs://notes/": {
        "backend": OceanbaseFsBackend(
            ob_client=ob_client,
            fs_root="/data/agent_notes",
            summarizer=LangChainSummarizer(
                llm=ChatAnthropic(model="claude-opus-4-5"),
                abstract_prompt="Return a one-sentence abstract of the document.",
                overview_prompt="Summarise the document in 3-5 bullet points.",
            ),
            embedder=LangChainEmbedder(
                embeddings=OpenAIEmbeddings(model="text-embedding-3-small"),
            ),
        ),
    },
})
```

`vfs.search(...)` fans out across every route sequentially and merges hits via the reranker.

## Exporting tools to your agent framework

```python
openai_tools    = vfs.tools.to_openai()
anthropic_tools = vfs.tools.to_anthropic()
langgraph_tools = vfs.tools.to_langgraph()   # needs [langgraph] extra
mcp_server      = vfs.tools.to_mcp()         # needs [mcp] extra
```
