"""RestRouters — every typed REST router, built over one Operations facade.

The surface mounts these; keeping their assembly here means a new concern's router
is added in one place and the surface does not import every route class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.rest.config import DisplayModeRoutes
from punt_lux.rest.display import DisplayRoutes
from punt_lux.rest.display_link import DisplayLinkRoutes
from punt_lux.rest.frame import FrameRoutes
from punt_lux.rest.menus import MenuRoutes
from punt_lux.rest.scenes import SceneRoutes
from punt_lux.rest.services import ServiceRoutes

if TYPE_CHECKING:
    from fastapi import APIRouter

    from punt_lux.operations import Operations
    from punt_lux.rest.route_deps import RouteDeps

__all__ = ["RestRouters"]


@final
class RestRouters:
    """The routers, one per concern, in mounting order."""

    _routers: tuple[APIRouter, ...]
    __slots__ = ("_routers",)

    def __new__(cls, ops: Operations, deps: RouteDeps) -> Self:
        self = super().__new__(cls)
        self._routers = (
            SceneRoutes(ops, deps.errors).router,
            MenuRoutes(ops, deps.errors).router,
            DisplayRoutes(deps).router,
            DisplayLinkRoutes(deps).router,
            FrameRoutes(deps).router,
            DisplayModeRoutes(ops, deps.errors).router,
            ServiceRoutes(ops, deps.errors).router,
        )
        return self

    @property
    def all(self) -> tuple[APIRouter, ...]:
        """The routers to mount, one per concern."""
        return self._routers
