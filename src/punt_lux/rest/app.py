"""The REST surface — the typed routers over one Operations facade.

luxd runs one FastAPI app; this module builds the typed routers that mount on it.
:class:`RestSurface` composes the concern route classes over a single facade so
the whole surface is one object to mount and one object to test: production
wires the facade from the Hub singletons via :meth:`RestSurface.for_hub`, and a
test constructs it over a facade backed by fakes. :class:`HubHealth` is the
typed body of the ``/health`` liveness probe, kept here with the surface it
belongs to; luxd fills its session count.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, final

from pydantic import BaseModel, ConfigDict

from punt_lux.hub_composition import HubComposition
from punt_lux.rest.config import DisplayModeRoutes
from punt_lux.rest.display import DisplayRoutes
from punt_lux.rest.frame import FrameRoutes
from punt_lux.rest.identity import RestCaller
from punt_lux.rest.menus import MenuRoutes
from punt_lux.rest.route_deps import RouteDeps
from punt_lux.rest.scenes import SceneRoutes
from punt_lux.rest.status import HttpErrorMap

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

    from punt_lux.operations import Operations

__all__ = ["HubHealth", "RestSurface"]


class HubHealth(BaseModel):
    """The hub liveness-probe body: process liveness plus the live session count.

    Reports only that luxd's process is up and how many MCP sessions it holds —
    not Hub store or replicator health; an unhealthy hub is no response at all,
    never a degraded status, so there is no discrimination beyond ``"ok"``.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    sessions: int


@final
class RestSurface:
    """Every typed REST router, composed over one Operations facade."""

    _routers: tuple[APIRouter, ...]
    _caller: RestCaller
    __slots__ = ("_caller", "_routers")

    def __new__(cls, ops: Operations) -> Self:
        self = super().__new__(cls)
        deps = RouteDeps(ops, HttpErrorMap())
        self._caller = RestCaller(ops, deps.errors)
        self._routers = (
            SceneRoutes(ops, deps.errors).router,
            MenuRoutes(ops, deps.errors).router,
            DisplayRoutes(deps).router,
            FrameRoutes(deps).router,
            DisplayModeRoutes(ops, deps.errors).router,
        )
        return self

    @classmethod
    def for_hub(cls) -> Self:
        """Wire the surface over the facade the Hub singletons compose."""
        HubComposition.bind_client_details()
        return cls(HubComposition.operations())

    @property
    def routers(self) -> tuple[APIRouter, ...]:
        """The routers to mount, one per concern."""
        return self._routers

    def mount(self, app: FastAPI) -> None:
        """Include every router on the app, and publish the per-request resolver.

        The write routes read the caller off ``app.state`` through the
        ``resolve_scope`` dependency, so one resolver serves the whole surface.
        """
        app.state.rest_caller = self._caller
        for router in self._routers:
            app.include_router(router)
