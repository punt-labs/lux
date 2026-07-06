"""InProcessLoop — the in-process Hub<->Display boundary rig.

Wires the production Display receive/wrap/emit logic (a windowless
``DisplayServer``) to the production Hub dispatch across the shipped
``InMemoryConnection`` duplex — the same ``Connection`` interface
``LineSocket`` implements, so the boundary is crossed through the real
abstraction, not around it. No socket, no subprocess, no GPU.

The rig owns exactly one genuinely new piece of wiring the design flags:
the queued interaction the Display's ``_emit_event`` produces is drained
and shipped over the ``InMemoryConnection`` (instead of the
``SocketServer`` client fds), then read back on the Hub end and handed to
the production ``ClientRegistry._hub_interaction_dispatch``. Everything
else — the wrap, the emit point, the Hub dispatch, the real handler,
``hub.publish``, the inbox — runs for real.

Interactions originate at the Display replica's own ``Element.fire`` — the
exact call ``ButtonRenderer.render`` makes on a real click — so the
``RemoteEventHandlerInvocation`` that crosses the wire is byte-identical
to a real click's by construction, not reconstructed. The only omitted
step is the GLFW pixel hit-test, explicitly deferred with the
screenshot layer (DES-028).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

from punt_lux.display.server import DisplayServer
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub import client_registry
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.in_memory_connection import InMemoryConnection
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.protocol import Element as WireElement

__all__ = ["InProcessLoop"]

# handle_scene ignores the owner fd (noqa ARG002 there); the rig has no
# socket, so any int stands in for the replica's owning client.
_REPLICA_OWNER_FD = 0


class InProcessLoop:
    """One windowless Display replica wired to the Hub over InMemoryConnection.

    Construct via ``InProcessLoop.start()``; tear down via ``close()``.
    The rig plays the Hub's Display-push leg (``push_scene``) and the
    Display's outbound-interaction leg (``cross``), leaving the Hub
    dispatch, handlers, pub-sub, and inbox to the production singletons.
    """

    _server: DisplayServer
    _display_conn: InMemoryConnection
    _hub_conn: InMemoryConnection
    _hub_reader: Iterator[dict[str, object]]
    _scene_id: str

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        raw_dir = tempfile.mkdtemp(prefix="lux-")
        self._server = DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))
        # Display end sends interactions; Hub end reads and dispatches them.
        self._display_conn, self._hub_conn = InMemoryConnection.paired()
        self._hub_reader = self._hub_conn.iter_lines()
        self._scene_id = ""
        return self

    @classmethod
    def start(cls) -> Self:
        """Return a started rig — the constructor does all the wiring."""
        return cls()

    @property
    def repush_client(self) -> _HubRepushClient:
        """Return the client double the Hub re-push resolves to.

        ``_hub_interaction_dispatch`` re-pushes the mutated scene through
        ``client_registry.get()``; the conftest points ``get`` at this
        double so the handler-driven re-push lands in the same replica the
        agent's own ``update`` re-pushes to — hermetic, no socket.
        """
        return _HubRepushClient(self)

    def push_scene(self, scene_id: str, roots: Sequence[DomainElement]) -> None:
        """Install a full scene replica into the windowless Display.

        Mirrors ``DisplayServer._handle_scene`` minus the socket ack: the
        authoritative roots cross the real ``SceneMessage`` wire codec
        (each ABC element as a pickled entry) to produce a separate replica
        graph, whose handlers are re-wrapped for remote dispatch through the
        Display's ``_emit_event``.
        """
        self._scene_id = scene_id
        # Every concrete kind satisfies both the domain Protocol and the
        # protocol wire union; the cast bridges the two names at the codec seam.
        wire_roots = cast("list[WireElement]", list(roots))
        outbound = SceneMessage(id=scene_id, elements=wire_roots)
        replica = message_from_dict(message_to_dict(outbound))
        assert isinstance(replica, SceneMessage)
        self._server._wrap_abc_elements(replica)
        # The wrap rebinds the Display's real ImGui factory; the rig never
        # renders, so re-bind the fail-loud sentinel to make "no render call"
        # a proven property — an accidental render() raises rather than passes.
        for elem in replica.elements:
            if isinstance(elem, AbcElement):
                elem.bind_renderer_factory(RaisingRendererFactory())
        self._server._scene_manager.handle_scene(replica, _REPLICA_OWNER_FD)
        self._server._route_to_domain_display(replica)
        # Render would set this before any click; the rig sets it so a
        # subsequently-fired interaction stamps the right scene_id.
        self._server._current_scene_id = scene_id

    def resolve_replica(self, element_id: str) -> AbcElement:
        """Return the replica element with ``element_id`` or raise.

        The element returned is the wrapped Display copy, so firing it
        drives the same ``RemoteDispatchGroup`` a real click drives.
        """
        scene = self._server._scene_manager.scenes.get(self._scene_id)
        if scene is None:
            msg = (
                f"scene {self._scene_id!r} absent from display replica "
                f"(cannot resolve element {element_id!r})"
            )
            raise LookupError(msg)
        for root in scene.elements:
            found = self._find(root, element_id)
            if found is not None:
                return found
        msg = f"element {element_id!r} not in display replica scene {self._scene_id!r}"
        raise LookupError(msg)

    def cross(self) -> tuple[RemoteEventHandlerInvocation, ...]:
        """Ship every queued Display interaction to the Hub and dispatch it.

        Drains the Display's ``_emit_event`` queue, sends each invocation
        over the ``InMemoryConnection``, reads it back on the Hub end
        through the shared ``Connection`` interface, and hands it to the
        production ``_hub_interaction_dispatch``. Returns the invocations as
        the Hub received them (loop invariant I1 asserts against these).
        """
        pending = tuple(self._server._event_queue)
        self._server._event_queue.clear()
        for invocation in pending:
            self._display_conn.send_line(message_to_dict(invocation))
        return tuple(self._dispatch_next() for _ in pending)

    def send_raw(self, invocation: RemoteEventHandlerInvocation) -> None:
        """Ship a hand-built (possibly malformed) invocation across the wire.

        Used only by the fail-closed security scenario: a real click can
        never produce a malformed invocation, so this is the sole path that
        feeds the Hub dispatch a hostile input to prove it denies by default.
        """
        self._display_conn.send_line(message_to_dict(invocation))
        self._dispatch_next()

    def inspect(self, scene_id: str) -> dict[str, object]:
        """Return the Display replica's enriched ``inspect_scene`` response."""
        return self._server._scene_inspector.inspect(scene_id)

    def close(self) -> None:
        """Close both ends of the duplex; idempotent."""
        self._display_conn.close()
        self._hub_conn.close()

    def _dispatch_next(self) -> RemoteEventHandlerInvocation:
        """Read one frame on the Hub end and run production dispatch on it."""
        received = message_from_dict(next(self._hub_reader))
        assert isinstance(received, RemoteEventHandlerInvocation)
        client_registry._hub_interaction_dispatch(received)
        return received

    def _find(self, element: object, element_id: str) -> AbcElement | None:
        """Search the replica subtree for ``element_id`` (None = not here).

        A genuine search primitive: absence within one subtree is a normal
        outcome the caller folds into a tree-wide raise, so ``None`` is the
        documented contract rather than a swallowed failure (PY-EH-8).
        """
        if not isinstance(element, AbcElement):
            return None
        if element.id == element_id:
            return element
        for child in element.child_elements():
            found = self._find(child, element_id)
            if found is not None:
                return found
        return None


class _HubRepushClient:
    """Client double the Hub re-push resolves to — routes to the replica.

    Satisfies the one call ``_hub_interaction_dispatch`` makes,
    ``show_async``, by re-installing the mutated scene into the rig's
    Display replica. Keeps the harness hermetic (no ``DisplayClient``
    socket connect) while still exercising the handler-driven re-push leg.
    """

    _rig: InProcessLoop

    def __new__(cls, rig: InProcessLoop) -> Self:
        self = super().__new__(cls)
        self._rig = rig
        return self

    def show_async(
        self,
        scene_id: str,
        *,
        elements: Sequence[DomainElement],
        frame_id: str | None = None,
        **_kwargs: object,
    ) -> None:
        """Re-install ``elements`` into the replica (the re-push leg)."""
        _ = frame_id
        self._rig.push_scene(scene_id, list(elements))
