from __future__ import annotations

import pytest

from seekvfs.exceptions import NotFoundError
from seekvfs.router import Router


def _route(marker: str) -> dict:
    return {"backend": marker, "generation": "skip"}  # content is opaque to Router


def test_longest_prefix_match_wins() -> None:
    routes = {
        "seekvfs://a/": _route("A"),
        "seekvfs://a/b/": _route("AB"),
        "seekvfs://a/b/c/": _route("ABC"),
    }
    r = Router(routes)
    _, cfg = r.resolve("seekvfs://a/b/c/leaf.md")
    assert cfg["backend"] == "ABC"
    _, cfg = r.resolve("seekvfs://a/b/other.md")
    assert cfg["backend"] == "AB"
    _, cfg = r.resolve("seekvfs://a/only.md")
    assert cfg["backend"] == "A"


def test_no_match_raises_notfound() -> None:
    r = Router({"seekvfs://foo/": _route("F")})
    with pytest.raises(NotFoundError):
        r.resolve("seekvfs://bar/baz.md")


def test_all_routes_sorted_desc() -> None:
    routes = {
        "seekvfs://a/": _route("A"),
        "seekvfs://a/b/": _route("AB"),
    }
    r = Router(routes)
    all_ = r.all_routes()
    assert len(all_[0][0]) >= len(all_[1][0])
