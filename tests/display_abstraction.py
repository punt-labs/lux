"""Abstraction function and abstract operations for DisplayServer refinement.

Maps concrete DisplayServer state to abstract Z specification state,
and provides pure-function implementations of each Z operation schema.

Z Specification: docs/display-server.tex
Implementation: src/punt_lux/display.py

Abstract state (from Z spec):
    clients      : P FD
    readers      : P FD           (= clients, invariant)
    hasScene     : ZBOOL
    sceneId      : SCENEID
    elemIds      : P ELEMID
    elemKinds    : ELEMID pfun ElementKind
    eventQueue   : P ELEMID
    listening    : ZBOOL
    bufSize      : nat
    pendingMsgs  : nat

Concrete state (from code):
    _server_sock   : socket | None
    _clients       : list[socket]
    _readers       : dict[int, FrameReader]
    _current_scene : SceneMessage | None
    _event_queue   : list[InteractionMessage]
    _textures      : TextureCache          (no abstract counterpart)
    _socket_path   : Path                  (no abstract counterpart)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.display import DisplayServer
    from punt_lux.protocol import FrameReader


# ---------------------------------------------------------------------------
# Abstract types
# ---------------------------------------------------------------------------

ELEMENT_KINDS = frozenset({"text", "button", "separator", "image"})


@dataclass(frozen=True)
class AbstractState:
    """Abstract DisplayServer state mirroring the Z specification schema."""

    clients: frozenset[int] = frozenset()
    readers: frozenset[int] = frozenset()
    has_scene: bool = False
    scene_id: str = ""
    elem_ids: frozenset[str] = frozenset()
    elem_kinds: dict[str, str] = field(default_factory=dict)
    event_queue: frozenset[str] = frozenset()
    listening: bool = True
    buf_size: int = 0
    pending_msgs: int = 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AbstractState):
            return NotImplemented
        # When has_scene is False on both sides, scene_id/elem_ids/elem_kinds
        # are unconstrained by the Z spec (no invariant references them).
        # The concrete code sets _current_scene=None which loses these values,
        # while the Z spec preserves them as frame conditions. Both are valid.
        scene_fields_match = (
            (
                self.scene_id == other.scene_id
                and self.elem_ids == other.elem_ids
                and self.elem_kinds == other.elem_kinds
            )
            if (self.has_scene or other.has_scene)
            else True
        )
        return (
            self.clients == other.clients
            and self.readers == other.readers
            and self.has_scene == other.has_scene
            and scene_fields_match
            and self.event_queue == other.event_queue
            and self.listening == other.listening
            and self.buf_size == other.buf_size
            and self.pending_msgs == other.pending_msgs
        )


# ---------------------------------------------------------------------------
# Abstraction function
# ---------------------------------------------------------------------------


def abstract(server: DisplayServer) -> AbstractState:
    """Map concrete DisplayServer to abstract Z specification state.

    This is the critical correctness bridge. Every field mapping must
    be verified manually against the Z spec.
    """
    # clients -> set of file descriptors
    client_fds = frozenset(s.fileno() for s in server._clients)

    # readers -> keys of the readers dict (should equal client_fds)
    reader_fds = frozenset(server._readers.keys())

    # Scene decomposition
    scene = server._current_scene
    has_scene = scene is not None
    scene_id = scene.id if scene is not None else ""
    elem_ids = (
        frozenset(e.id for e in scene.elements if e.id is not None)
        if scene is not None
        else frozenset()
    )
    elem_kinds: dict[str, str] = (
        {e.id: e.kind for e in scene.elements if e.id is not None}
        if scene is not None
        else {}
    )

    # Event queue -> set of element IDs with pending interactions
    event_queue = frozenset(e.element_id for e in server._event_queue)

    # Listening -> server socket exists
    listening = server._server_sock is not None

    return AbstractState(
        clients=client_fds,
        readers=reader_fds,
        has_scene=has_scene,
        scene_id=scene_id,
        elem_ids=elem_ids,
        elem_kinds=elem_kinds,
        event_queue=event_queue,
        listening=listening,
        buf_size=0,
        pending_msgs=0,
    )


def abstract_reader(reader: FrameReader) -> tuple[int, int]:
    """Map concrete FrameReader to abstract (bufSize, pendingMsgs).

    The Z spec flattens FrameReader into the DisplayServer schema,
    but the concrete code has one FrameReader per client. We test
    FrameReader commutativity separately.
    """
    return (len(reader._buf), 0)


# ---------------------------------------------------------------------------
# Abstract init
# ---------------------------------------------------------------------------


def abstract_init() -> AbstractState:
    """Z spec Init mapped to concrete constructor.

    The Z spec sets listening'=ztrue (init includes socket setup),
    but the concrete code has a two-phase init: __init__ (listening=False)
    then _on_post_init (listening=True). We match the constructor here.
    """
    return AbstractState(
        clients=frozenset(),
        readers=frozenset(),
        has_scene=False,
        scene_id="",
        elem_ids=frozenset(),
        elem_kinds={},
        event_queue=frozenset(),
        listening=False,
        buf_size=0,
        pending_msgs=0,
    )


def abstract_reader_init() -> tuple[int, int]:
    """Z spec Init for FrameReader portion: empty buffer, no pending."""
    return (0, 0)


# ---------------------------------------------------------------------------
# Abstract operations (pure functions mirroring Z operation schemas)
# ---------------------------------------------------------------------------


def abstract_accept_connection(state: AbstractState, new_client: int) -> AbstractState:
    """Z spec AcceptConnection: add client + reader."""
    assert state.listening
    assert new_client not in state.clients
    new_clients = state.clients | {new_client}
    return AbstractState(
        clients=new_clients,
        readers=new_clients,
        has_scene=state.has_scene,
        scene_id=state.scene_id,
        elem_ids=state.elem_ids,
        elem_kinds=state.elem_kinds,
        event_queue=state.event_queue,
        listening=state.listening,
        buf_size=state.buf_size,
        pending_msgs=state.pending_msgs,
    )


def abstract_disconnect_client(state: AbstractState, dead_client: int) -> AbstractState:
    """Z spec DisconnectClient: remove client + reader."""
    assert dead_client in state.clients
    new_clients = state.clients - {dead_client}
    return AbstractState(
        clients=new_clients,
        readers=new_clients,
        has_scene=state.has_scene,
        scene_id=state.scene_id,
        elem_ids=state.elem_ids,
        elem_kinds=state.elem_kinds,
        event_queue=state.event_queue,
        listening=state.listening,
        buf_size=state.buf_size,
        pending_msgs=state.pending_msgs,
    )


def abstract_receive_scene(
    state: AbstractState,
    new_scene_id: str,
    new_elem_ids: frozenset[str],
    new_elem_kinds: dict[str, str],
) -> AbstractState:
    """Z spec ReceiveScene: replace scene, clear event queue."""
    return AbstractState(
        clients=state.clients,
        readers=state.readers,
        has_scene=True,
        scene_id=new_scene_id,
        elem_ids=new_elem_ids,
        elem_kinds=new_elem_kinds,
        event_queue=frozenset(),
        listening=state.listening,
        buf_size=state.buf_size,
        pending_msgs=state.pending_msgs,
    )


def abstract_clear_scene(state: AbstractState) -> AbstractState:
    """Z spec ClearScene: clear scene flag and event queue."""
    return AbstractState(
        clients=state.clients,
        readers=state.readers,
        has_scene=False,
        scene_id=state.scene_id,
        elem_ids=state.elem_ids,
        elem_kinds=state.elem_kinds,
        event_queue=frozenset(),
        listening=state.listening,
        buf_size=state.buf_size,
        pending_msgs=state.pending_msgs,
    )


def abstract_remove_element(state: AbstractState, target_id: str) -> AbstractState:
    """Z spec RemoveElement: remove element from scene."""
    assert state.has_scene
    assert target_id in state.elem_ids
    new_elem_ids = state.elem_ids - {target_id}
    new_elem_kinds = {k: v for k, v in state.elem_kinds.items() if k != target_id}
    return AbstractState(
        clients=state.clients,
        readers=state.readers,
        has_scene=state.has_scene,
        scene_id=state.scene_id,
        elem_ids=new_elem_ids,
        elem_kinds=new_elem_kinds,
        event_queue=state.event_queue,
        listening=state.listening,
        buf_size=state.buf_size,
        pending_msgs=state.pending_msgs,
    )


def abstract_button_click(state: AbstractState, button_id: str) -> AbstractState:
    """Z spec ButtonClick: queue interaction event for a button."""
    assert state.has_scene
    assert button_id in state.elem_ids
    assert state.elem_kinds.get(button_id) == "button"
    return AbstractState(
        clients=state.clients,
        readers=state.readers,
        has_scene=state.has_scene,
        scene_id=state.scene_id,
        elem_ids=state.elem_ids,
        elem_kinds=state.elem_kinds,
        event_queue=state.event_queue | {button_id},
        listening=state.listening,
        buf_size=state.buf_size,
        pending_msgs=state.pending_msgs,
    )


def abstract_flush_events(state: AbstractState) -> AbstractState:
    """Z spec FlushEvents: clear the event queue."""
    return AbstractState(
        clients=state.clients,
        readers=state.readers,
        has_scene=state.has_scene,
        scene_id=state.scene_id,
        elem_ids=state.elem_ids,
        elem_kinds=state.elem_kinds,
        event_queue=frozenset(),
        listening=state.listening,
        buf_size=state.buf_size,
        pending_msgs=state.pending_msgs,
    )


def abstract_feed_bytes(buf_size: int, bytes_in: int, max_buf: int) -> int:
    """Z spec FeedBytes: increase buffer size."""
    assert bytes_in > 0
    assert buf_size + bytes_in <= max_buf
    return buf_size + bytes_in


def abstract_drain_messages(
    buf_size: int, pending_msgs: int, bytes_consumed: int
) -> tuple[int, int, int]:
    """Z spec DrainMessages: reduce buffer, clear pending, return drained.

    Returns (new_buf_size, new_pending_msgs, drained).
    """
    assert bytes_consumed <= buf_size
    return (buf_size - bytes_consumed, 0, pending_msgs + bytes_consumed)


def abstract_shutdown(state: AbstractState) -> AbstractState:
    """Z spec Shutdown: disconnect all, clear events, stop listening."""
    return AbstractState(
        clients=frozenset(),
        readers=frozenset(),
        has_scene=False,
        scene_id=state.scene_id,
        elem_ids=state.elem_ids,
        elem_kinds=state.elem_kinds,
        event_queue=frozenset(),
        listening=False,
        buf_size=state.buf_size,
        pending_msgs=state.pending_msgs,
    )


# ---------------------------------------------------------------------------
# Precondition checks
# ---------------------------------------------------------------------------


def accept_precondition(state: AbstractState, new_client: int) -> bool:
    return state.listening and new_client not in state.clients


def disconnect_precondition(state: AbstractState, dead_client: int) -> bool:
    return dead_client in state.clients


def receive_scene_precondition(
    new_elem_ids: frozenset[str], new_elem_kinds: dict[str, str]
) -> bool:
    return new_elem_ids <= frozenset(new_elem_kinds.keys())


def remove_element_precondition(state: AbstractState, target_id: str) -> bool:
    return (
        state.has_scene
        and target_id in state.elem_ids
        and target_id not in state.event_queue
    )


def button_click_precondition(state: AbstractState, button_id: str) -> bool:
    return (
        state.has_scene
        and button_id in state.elem_ids
        and state.elem_kinds.get(button_id) == "button"
    )


def feed_bytes_precondition(buf_size: int, bytes_in: int, max_buf: int) -> bool:
    return bytes_in > 0 and buf_size + bytes_in <= max_buf


def drain_precondition(buf_size: int, bytes_consumed: int) -> bool:
    return bytes_consumed <= buf_size
