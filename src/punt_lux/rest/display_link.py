"""The display-link route -- the Hub's observed link state, proxied over REST.

Split from :mod:`punt_lux.rest.display` (one concern, one module): unlike the
rest of that router, ``get_link`` never proxies to the display -- it is a
pure Hub-local classification (design display-presence-demand-driven.md §6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from fastapi import APIRouter

from punt_lux.operations.models.display_link import DisplayLinkState

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.route_deps import RouteDeps

__all__ = ["DisplayLinkRoutes"]


@final
class DisplayLinkRoutes:
    """The one route: the Hub's observed display-link state."""

    _ops: Operations
    _router: APIRouter
    __slots__ = ("_ops", "_router")

    def __new__(cls, deps: RouteDeps) -> Self:
        self = super().__new__(cls)
        self._ops = deps.ops
        router = APIRouter(tags=["display"])
        router.add_api_route("/display/link", self.get_link, methods=["GET"])
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def get_link(self) -> DisplayLinkState:
        """Return the Hub's observed display-link state; never round-trips or faults.

        Unlike every other route, this one never returns ``OpError`` -- so it
        returns the operation's result directly, with no ``HttpErrorMap.respond``
        wrapper to unwrap a failure case that cannot occur.
        """
        return self._ops.get_link()
