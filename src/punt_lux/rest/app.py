"""The REST surface — the typed routers over one Operations facade.

luxd runs one FastAPI app; this module builds the typed routers that mount on it.
:class:`RestSurface` composes the concern route classes over a single facade so
the whole surface is one object to mount and one object to test: production wires
the facade from the Hub singletons via :meth:`RestSurface.for_hub`, and a test
constructs it over a facade backed by fakes.

:class:`HubHealth` is the typed body of the ``/health`` liveness probe, kept here
with the surface it belongs to; luxd fills its session count.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, final

from pydantic import BaseModel, ConfigDict

from punt_lux.domain.hub import client_registry, hub, hub_display
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, next_event
from punt_lux.domain.hub.replicator_instance import hub_menu_registry, hub_replicator
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import HubPorts, Operations, Scope
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.paths import DisplayPaths
from punt_lux.rest.config import DisplayModeRoutes
from punt_lux.rest.display import DisplayRoutes
from punt_lux.rest.menus import MenuRoutes
from punt_lux.rest.scenes import SceneRoutes
from punt_lux.rest.status import HttpErrorMap

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

__all__ = ["DEFAULT_SCOPE", "HubHealth", "RestSurface"]

# A connection-less REST request lands in one default Hub scope for this unit.
# Per-caller scoping arrives with the multi-user future, when a REST call carries
# an explicit session identity.
DEFAULT_SCOPE = Scope(ConnectionId("rest"))


class HubHealth(BaseModel):
    """The hub liveness-probe body: process liveness plus the live session count.

    This reports only that luxd's process is up and how many MCP sessions it
    holds — not the health of the Hub store or the background replicator. An
    unhealthy hub is observed as no response at all, not as a degraded status
    here; there is no status discrimination beyond ``"ok"``.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    sessions: int


@final
class RestSurface:
    """Every typed REST router, composed over one Operations facade."""

    _routers: tuple[APIRouter, ...]
    __slots__ = ("_routers",)

    def __new__(cls, ops: Operations, *, scope: Scope) -> Self:
        self = super().__new__(cls)
        errors = HttpErrorMap()
        self._routers = (
            SceneRoutes(ops, scope, errors).router,
            MenuRoutes(ops, scope, errors).router,
            DisplayRoutes(ops, errors).router,
            DisplayModeRoutes(ops, errors).router,
        )
        return self

    @classmethod
    def for_hub(cls) -> Self:
        """Wire the surface over the facade the Hub singletons compose."""
        return cls(cls._hub_operations(), scope=DEFAULT_SCOPE)

    @staticmethod
    def _hub_operations() -> Operations:
        """Compose the operations facade from the Hub's process singletons."""
        ports = HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=ensure_writer,
            next_event=next_event,
        )
        display_port = HubDisplayConnection(
            is_running=lambda: DisplayPaths().is_running(),
            clients=client_registry,
        )
        return Operations.for_store(
            hub_display,
            hub_replicator,
            hub=hub,
            client_registry=client_registry,
            menu_registry=hub_menu_registry,
            ports=ports,
            display_port=display_port,
        )

    @property
    def routers(self) -> tuple[APIRouter, ...]:
        """The routers to mount, one per concern."""
        return self._routers

    def mount(self, app: FastAPI) -> None:
        """Include every router on the given FastAPI app."""
        for router in self._routers:
            app.include_router(router)
