"""Longest-prefix URI router.

Given a dict of URI-prefix -> RouteConfig, ``Router.resolve(uri)`` returns
the matching config by longest-prefix. The router never mutates paths; it
only inspects prefixes.
"""
from __future__ import annotations

from seekvfs.exceptions import NotFoundError
from seekvfs.models import RouteConfig


class Router:
    def __init__(self, routes: dict[str, RouteConfig]) -> None:
        # sort descending by length for longest-prefix match
        self._sorted: list[tuple[str, RouteConfig]] = sorted(
            routes.items(), key=lambda kv: len(kv[0]), reverse=True
        )
        self._routes = dict(routes)

    def resolve(self, uri: str) -> tuple[str, RouteConfig]:
        """Return ``(prefix, route)`` for the longest prefix matching ``uri``.

        Raises :class:`NotFoundError` when no route matches.
        """
        for prefix, route in self._sorted:
            if uri.startswith(prefix):
                return prefix, route
        raise NotFoundError(f"no route matches uri {uri!r}")

    def all_routes(self) -> list[tuple[str, RouteConfig]]:
        return list(self._sorted)


__all__ = ["Router"]
