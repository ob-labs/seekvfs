# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-27

Initial release.

### Core

- `VFS` facade: URI normalization, longest-prefix routing across multiple
  backends, cross-backend search fan-out with pluggable reranker, and
  lifecycle forwarding (`initialize` / `close`, context-manager support).
- Custom URI scheme: pass `scheme=` to `VFS(...)` to use your own namespace
  (default `seekvfs://`).
- Agent tool export via `vfs.tools`: 8 neutral tool specs (`search`, `read`,
  `read_full`, `write`, `edit`, `ls`, `grep`, `delete`) with adapters for
  OpenAI, Anthropic, LangGraph, and MCP.

### Recipes

- `seekvfs_recipes.minimal`: one-file-per-path local-disk backend for the
  smallest persistent setup.
- `seekvfs_recipes.maximal`: tiered storage (L2 on filesystem, L0/L1 plus
  embeddings in OceanBase) with semantic search, summarization, and
  reconciliation.

### Packaging

- Python 3.11 / 3.12 / 3.13 support.
- PEP 561 typing marker (`py.typed`) shipped in both top-level packages.
- Optional extras: `[observability]` (logfire), `[full]` (maximal recipe
  dependencies + all agent-framework integrations), `[dev]`.
