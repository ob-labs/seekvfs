"""Maximal recipe — L2 on filesystem, L0/L1/embedding in OceanBase.

The full-featured built-in backend. Handles summarization, embedding,
background derivative generation, and reconciliation so agents can do
"read short first, read full on demand" plus vector search out of the box.

Storage layout:
- L2 full content      → local filesystem (``fs_root`` directory)
- L0 abstract (~100 t) → OceanBase ``files`` table
- L1 overview (~2k t)  → OceanBase ``files`` table
- embedding            → OceanBase ``files`` table (VECTOR column)

Owns its own protocols (:class:`Summarizer`, :class:`Embedder`) and its
own ``TierNotAvailable`` exception; the core protocol layer does not know
about tiers.

Full guide: ``docs/recipes/maximal.md``.
Schema & customisation: ``src/seekvfs_recipes/maximal/dao.py``.
"""
from __future__ import annotations

from seekvfs_recipes.maximal.backend import GenerationMode, OceanbaseFsBackend
from seekvfs_recipes.maximal.dao import VfsStorageDAO
from seekvfs_recipes.maximal.embedder import LangChainEmbedder
from seekvfs_recipes.maximal.exceptions import TierNotAvailable
from seekvfs_recipes.maximal.protocol import Embedder, Summarizer
from seekvfs_recipes.maximal.reconcile import ReconcileStats, reconcile
from seekvfs_recipes.maximal.summarizer import LangChainSummarizer

__all__ = [
    "OceanbaseFsBackend",
    "GenerationMode",
    "VfsStorageDAO",
    "Summarizer",
    "Embedder",
    "LangChainSummarizer",
    "LangChainEmbedder",
    "TierNotAvailable",
    "reconcile",
    "ReconcileStats",
]
