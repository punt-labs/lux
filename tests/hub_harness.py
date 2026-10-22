"""IsolatedHub — a process-local Hub for tests that drive the real dispatch.

``HubInteractionDispatch`` resolves the element against the module-level
``hub_display`` singleton and marks the scene dirty on the module-level
``hub_replicator``. A test that wants the real dispatch without a live luxd
swaps both for its own, which is what this class owns: it holds the isolated
``HubDisplay``, the recording replicator stand-in, and the wire-message
construction, so a test reads as install-then-click rather than as four lines
of monkeypatching repeated per case.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final
from unittest.mock import MagicMock

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_interaction_dispatch import HubInteractionDispatch
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    import pytest

    from punt_lux.domain.element import Element as WireElement

__all__ = ["IsolatedHub"]


@final
class IsolatedHub:
    """A test-local ``HubDisplay`` wired in place of the process singletons."""

    display: HubDisplay
    replicator: MagicMock
    __slots__ = ("display", "replicator")

    def __new__(cls, monkeypatch: pytest.MonkeyPatch) -> Self:
        import punt_lux.domain.hub as hub_module

        self = super().__new__(cls)
        self.display = HubDisplay()
        self.replicator = MagicMock()
        monkeypatch.setattr(hub_module, "hub_display", self.display)
        monkeypatch.setattr(
            "punt_lux.domain.hub.replicator_instance.hub_replicator", self.replicator
        )
        return self

    def connect(self, name: str) -> ConnectionId:
        """Register a connection as a Hub client and return its id."""
        connection_id = ConnectionId(name)
        self.display.register_client(connection_id)
        return connection_id

    def install(
        self,
        owner: ConnectionId,
        scene_id: SceneId,
        element: WireElement,
    ) -> None:
        """Install ``element`` as a root of ``scene_id`` owned by ``owner``."""
        self.display.apply(
            owner, AddElement(scene_id=scene_id, element=element, parent_id=None)
        )

    def click(
        self,
        scene_id: SceneId,
        element_id: ElementId,
        *,
        event_kind: str | None = "button_clicked",
        value: object = True,
    ) -> None:
        """Drive one display-originated interaction through the real dispatch."""
        self.dispatch(
            RemoteEventHandlerInvocation(
                scene_id=str(scene_id),
                element_id=str(element_id),
                action=str(element_id),
                event_kind=event_kind,
                ts=1.0,
                value=value,
            )
        )

    def dispatch(self, msg: RemoteEventHandlerInvocation) -> None:
        """Route a caller-built invocation through ``HubInteractionDispatch``."""
        HubInteractionDispatch.dispatch(msg)

    def dirtied(self) -> list[SceneId]:
        """Return the scenes the dispatch marked dirty, in call order."""
        return [call.args[0] for call in self.replicator.mark_dirty.call_args_list]
