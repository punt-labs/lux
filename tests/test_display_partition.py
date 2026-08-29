"""TTF partition tests for RenderLoop Z specification.

Derived from docs/display-server.tex using Test Template Framework tactics.
Each test corresponds to a distinct behavioral partition — a unique combination
of precondition boundary and state configuration that must be tested for full
spec-implementation conformance.

Partition classes:
    Happy path     — typical mid-range values
    Boundary       — at or near constraint limits
    REJECTED       — precondition violation (operation should not execute)
    INVARIANT      — exercises state invariant boundaries
"""

from __future__ import annotations

from typing import Literal
from unittest.mock import MagicMock

from punt_lux.display import RenderLoop
from punt_lux.display.render_loop import _ORPHAN_FD
from punt_lux.protocol import (
    ButtonElement,
    ConnectMessage,
    FrameReader,
    PingMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    SeparatorElement,
    TextElement,
    encode_message,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _server() -> RenderLoop:
    return RenderLoop("/tmp/test-lux-partition.sock")


def _scene_count(server: RenderLoop) -> int:
    """Total scenes the display holds, across every frame."""
    return server._scenes.scene_count


def _active_scene_id(server: RenderLoop) -> str | None:
    """The abstract active scene: the first frame's active tab, or None."""
    return server._scenes.active_scene_id


def _scene(server: RenderLoop, scene_id: str) -> SceneMessage:
    """Return the framed scene with ``scene_id`` (asserting it is present)."""
    resolved = server._scenes.resolve_scene(scene_id)
    assert resolved is not None, f"scene {scene_id!r} absent from the display"
    return resolved


def _sock(fd: int = 42) -> MagicMock:
    s = MagicMock()
    s.send.side_effect = len  # a real socket accepts the bytes and returns the count
    s.fileno.return_value = fd
    s.close = MagicMock()
    return s


def _register(server: RenderLoop, sock: MagicMock) -> None:
    server._socket_listener.clients.append(sock)
    server._socket_listener._readers[sock.fileno()] = FrameReader()


def _scene_with(
    scene_id: str, *elems: TextElement | ButtonElement | SeparatorElement
) -> SceneMessage:
    return SceneMessage(id=scene_id, elements=list(elems), frame_id=scene_id)


def _inject_scene(server: RenderLoop, scene: SceneMessage) -> None:
    # Every scene is framed; install it through the frame book like the display's
    # own scene handler does (the scene self-frames by its id via _scene_with).
    server._scenes.handle_framed_scene(scene, owner_fd=0)


def _clear_all_scenes(server: RenderLoop) -> None:
    server._scenes.clear_all()


# ---------------------------------------------------------------------------
# AcceptConnection (6 partitions)
# Preconditions: listening, newClient not in clients, capacity available
# ---------------------------------------------------------------------------


class TestAcceptConnectionPartitions:
    """AcceptConnection: 3 accepted, 3 rejected."""

    def test_accept_1_happy_path_empty_server(self):
        """P1: Accept first client into empty server."""
        server = _server()
        sock = _sock(fd=10)
        assert len(server._socket_listener.clients) == 0
        _register(server, sock)
        assert len(server._socket_listener.clients) == 1
        assert 10 in server._socket_listener._readers

    def test_accept_2_one_existing_client(self):
        """P2: Accept second client when one already connected."""
        server = _server()
        _register(server, _sock(fd=10))
        sock2 = _sock(fd=20)
        _register(server, sock2)
        assert len(server._socket_listener.clients) == 2
        assert {10, 20} == set(server._socket_listener._readers.keys())

    def test_accept_3_boundary_fills_to_max(self):
        """P3: Accept client when at maxClients-1 (reaches capacity).
        maxClients=3 in spec, so accept 3rd into server with 2."""
        server = _server()
        _register(server, _sock(fd=10))
        _register(server, _sock(fd=20))
        sock3 = _sock(fd=30)
        _register(server, sock3)
        assert len(server._socket_listener.clients) == 3

    def test_accept_4_rejected_not_listening(self):
        """REJECTED ¬P1: Server not listening (server_sock is None).
        In concrete code, _accept_connections() returns early."""
        server = _server()
        assert server._socket_listener.server_sock is None  # not listening
        # accept_connections is a no-op when not listening
        server._socket_listener.accept_connections()
        assert len(server._socket_listener.clients) == 0

    def test_accept_5_rejected_duplicate_fd(self):
        """REJECTED ¬P2: Client FD already in clients set.
        Concrete code: select() wouldn't offer duplicate, but verify
        that reader dict is keyed by fd (duplicate would overwrite)."""
        server = _server()
        sock1 = _sock(fd=10)
        _register(server, sock1)
        reader1 = server._socket_listener._readers[10]
        # Re-registering same fd overwrites the reader
        _register(server, _sock(fd=10))
        assert server._socket_listener._readers[10] is not reader1

    def test_accept_6_rejected_at_capacity(self):
        """REJECTED ¬P3: Server at maxClients capacity.
        Concrete code doesn't enforce hard limit — this partition
        documents the spec constraint for awareness."""
        server = _server()
        for fd in range(10, 13):
            _register(server, _sock(fd=fd))
        assert len(server._socket_listener.clients) == 3  # at max


# ---------------------------------------------------------------------------
# DisconnectClient (4 partitions)
#
# Preconditions:
#   P1: deadClient? ∈ clients
# ---------------------------------------------------------------------------


class TestDisconnectClientPartitions:
    """DisconnectClient: 3 accepted, 1 rejected."""

    def test_disconnect_1_single_client(self):
        """P1: Disconnect sole client -> empty server."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener.remove_client(sock)
        assert len(server._socket_listener.clients) == 0
        assert 10 not in server._socket_listener._readers

    def test_disconnect_2_one_of_two(self):
        """P2: Disconnect one of two clients -> one remains."""
        server = _server()
        sock1, sock2 = _sock(fd=10), _sock(fd=20)
        _register(server, sock1)
        _register(server, sock2)
        server._socket_listener.remove_client(sock1)
        assert len(server._socket_listener.clients) == 1
        assert 20 in server._socket_listener._readers
        assert 10 not in server._socket_listener._readers

    def test_disconnect_3_preserves_scene(self):
        """P3: Disconnect does not affect current scene or events."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        _inject_scene(server, _scene_with("s1", TextElement(id="t1", content="A")))
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="t1", action="click", ts=1.0)
        )
        server._socket_listener.remove_client(sock)
        assert _scene_count(server) > 0
        assert len(server._event_queue) == 1

    def test_disconnect_4_rejected_not_connected(self):
        """REJECTED ¬P1: deadClient not in clients.
        _remove_client on unknown socket is safe no-op."""
        server = _server()
        unknown = _sock(fd=99)
        server._socket_listener.remove_client(unknown)
        assert len(server._socket_listener.clients) == 0


# ---------------------------------------------------------------------------
# ReceiveScene (6 partitions)
#
# Preconditions:
#   P1: newElemIds? ⊆ dom newElemKinds?
#   P2: #newElemIds? ≤ maxElements
# ---------------------------------------------------------------------------


class TestReceiveScenePartitions:
    """ReceiveScene: 4 accepted, 2 rejected (implicit)."""

    def test_scene_1_happy_path_first_scene(self):
        """P1: Receive first scene with 1 element."""
        server = _server()
        sock = _sock()
        scene = _scene_with("s1", TextElement(id="t1", content="Hi"))
        server._handle_message(sock, scene)
        assert _scene_count(server) > 0
        assert _active_scene_id(server) == "s1"
        assert len(_scene(server, "s1").elements) == 1

    def test_scene_2_boundary_max_elements(self):
        """P2: Receive scene with maxElements(3) elements."""
        server = _server()
        sock = _sock()
        scene = _scene_with(
            "s1",
            TextElement(id="t1", content="A"),
            ButtonElement(id="b1", label="B"),
            SeparatorElement(id="sep1"),
        )
        server._handle_message(sock, scene)
        assert _scene_count(server) > 0
        assert len(_scene(server, "s1").elements) == 3

    def test_scene_3_new_id_preserves_events(self):
        """P3: New scene (different ID) preserves existing events."""
        server = _server()
        sock = _sock()
        old_scene = _scene_with("s1", ButtonElement(id="b1", label="Old"))
        server._handle_message(sock, old_scene)
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="click", ts=1.0)
        )
        assert len(server._event_queue) == 1

        new_scene = _scene_with("s2", TextElement(id="t2", content="New"))
        server._handle_message(sock, new_scene)
        assert _scene_count(server) > 0
        assert server._scenes.resolve_scene("s2") is not None
        assert len(server._event_queue) == 1  # events from s1 persist

    def test_scene_4_empty_scene_is_not_stored(self):
        """P4: an empty-element push is the Hub's removal signal, not a stored scene.

        Under the frame/scene lifecycle ruling, content and frame appear and
        disappear together — an empty push never lingers as a husk scene.
        """
        server = _server()
        sock = _sock()
        server._handle_message(sock, SceneMessage(id="s1", elements=[], frame_id="s1"))
        assert server._scenes.resolve_scene("s1") is None

    def test_scene_5_all_element_kinds(self):
        """P5: Scene with all 4 element kinds (text, button, separator, image).
        Exercises elemKinds coverage invariant (I6)."""
        server = _server()
        sock = _sock()
        # Note: only 3 elements fit in maxElements for spec, but
        # concrete code doesn't enforce the bound
        scene = _scene_with(
            "s1",
            TextElement(id="t1", content="A"),
            ButtonElement(id="b1", label="B"),
            SeparatorElement(id="sep1"),
        )
        server._handle_message(sock, scene)
        assert _scene_count(server) > 0
        kinds = {e.kind for e in _scene(server, "s1").elements}
        assert kinds == {"text", "button", "separator"}

    def test_scene_6_idempotent_same_scene_id(self):
        """P6: Receive scene with same ID as current (full replacement)."""
        server = _server()
        sock = _sock()
        scene1 = _scene_with("s1", TextElement(id="t1", content="V1"))
        server._handle_message(sock, scene1)
        scene2 = _scene_with("s1", TextElement(id="t1", content="V2"))
        server._handle_message(sock, scene2)
        assert _scene_count(server) > 0
        elem = _scene(server, "s1").elements[0]
        assert isinstance(elem, TextElement)
        assert elem.content == "V2"


# ---------------------------------------------------------------------------
# ClearScene (3 partitions — no preconditions)
# ---------------------------------------------------------------------------


class TestClearScenePartitions:
    """ClearScene: 3 accepted, 0 rejected."""

    def test_clear_1_with_scene(self):
        """P1: Clear existing scene."""
        server = _server()
        sock = _sock()
        server._handle_message(
            sock, _scene_with("s1", TextElement(id="t1", content="A"))
        )
        server._handle_clear()
        assert _scene_count(server) == 0

    def test_clear_2_idempotent_no_scene(self):
        """P2: Clear when no scene exists (idempotent)."""
        server = _server()
        server._handle_clear()
        assert _scene_count(server) == 0

    def test_clear_3_clears_event_queue(self):
        """P3: Clear also drains the event queue (I7 preservation)."""
        server = _server()
        sock = _sock()
        server._handle_message(
            sock,
            _scene_with("s1", ButtonElement(id="b1", label="X")),
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="click", ts=1.0)
        )
        server._handle_clear()
        assert len(server._event_queue) == 0


class TestButtonClickPartitions:
    """ButtonClick: 3 accepted, 4 rejected.

    Note: ButtonClick is triggered by ImGui rendering, which we can't
    call in unit tests. We test the event queue directly.
    """

    def test_click_1_happy_path_empty_queue(self):
        """P1: Click button with empty event queue."""
        server = _server()
        _inject_scene(server, _scene_with("s1", ButtonElement(id="b1", label="Go")))
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=1.0, value=True
            )
        )
        assert len(server._event_queue) == 1
        assert server._event_queue[0].element_id == "b1"

    def test_click_2_queue_has_existing_events(self):
        """P2: Click button when queue already has events."""
        server = _server()
        _inject_scene(
            server,
            _scene_with(
                "s1",
                ButtonElement(id="b1", label="A"),
                ButtonElement(id="b2", label="B"),
            ),
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=1.0, value=True
            )
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b2", action="b2", ts=2.0, value=True
            )
        )
        assert len(server._event_queue) == 2
        elem_ids = {e.element_id for e in server._event_queue}
        assert elem_ids == {"b1", "b2"}

    def test_click_3_boundary_fills_queue(self):
        """P3 BOUNDARY: Queue at maxEvents-1, click fills to max."""
        server = _server()
        _inject_scene(
            server,
            _scene_with(
                "s1",
                ButtonElement(id="b1", label="A"),
                ButtonElement(id="b2", label="B"),
                ButtonElement(id="b3", label="C"),
            ),
        )
        # Pre-fill to maxEvents-1 = 2
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=1.0, value=True
            )
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b2", action="b2", ts=2.0, value=True
            )
        )
        # One more fills to maxEvents=3
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b3", action="b3", ts=3.0, value=True
            )
        )
        assert len(server._event_queue) == 3  # at max

    def test_click_4_rejected_no_scene(self):
        """REJECTED ¬P1: No scene -> no button to click.
        Concrete code: _render_scene shows "waiting" text, no buttons."""
        server = _server()
        assert _scene_count(server) == 0
        # No buttons rendered, so no events can be queued
        assert len(server._event_queue) == 0

    def test_click_5_rejected_nonexistent_element(self):
        """REJECTED ¬P2: buttonId not in elemIds.
        Concrete code: button doesn't exist in scene, never rendered."""
        server = _server()
        _inject_scene(
            server, _scene_with("s1", TextElement(id="t1", content="No buttons"))
        )
        # No buttons in scene, so no button click events possible
        assert len(server._event_queue) == 0

    def test_click_6_rejected_wrong_kind(self):
        """REJECTED ¬P3: Element exists but is not a button.
        Text elements don't generate click events."""
        server = _server()
        _inject_scene(
            server, _scene_with("s1", TextElement(id="t1", content="Not clickable"))
        )
        # Text elements don't produce interaction events
        # (only buttons have click handling in _render_button)
        assert len(server._event_queue) == 0

    def test_click_7_idempotent_same_button_twice(self):
        """P7: Same button clicked twice -> both events queued.
        The Z spec uses sets (eventQueue : P ELEMID), so duplicates
        collapse. Concrete code uses a list, so both are kept."""
        server = _server()
        _inject_scene(server, _scene_with("s1", ButtonElement(id="b1", label="X")))
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=1.0, value=True
            )
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=2.0, value=True
            )
        )
        # Concrete: list preserves both. Spec: set collapses to {b1}.
        # This is a known abstraction gap (set vs list).
        assert len(server._event_queue) == 2


# ---------------------------------------------------------------------------
# FlushEvents (2 partitions — no preconditions)
# ---------------------------------------------------------------------------


class TestFlushEventsPartitions:
    """FlushEvents: 2 accepted, 0 rejected."""

    def test_flush_1_with_events(self):
        """P1: Flush non-empty queue -> queue emptied."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        _inject_scene(server, _scene_with("s1", ButtonElement(id="b1", label="X")))
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="click", ts=1.0)
        )
        server._flush_events()
        assert len(server._event_queue) == 0

    def test_flush_2_empty_queue(self):
        """P2: Flush empty queue -> no-op."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._flush_events()
        assert len(server._event_queue) == 0
        sock.send.assert_not_called()


# ---------------------------------------------------------------------------
# FeedBytes (6 partitions)
#
# Preconditions:
#   P1: bytesIn? > 0
#   P2: bytesIn? ≤ maxBufSize
#   P3: bufSize + bytesIn? ≤ maxBufSize
# ---------------------------------------------------------------------------


class TestFeedBytesPartitions:
    """FeedBytes: 3 accepted, 3 rejected."""

    def test_feed_1_happy_path_empty_buffer(self):
        """P1: Feed bytes into empty buffer."""
        reader = FrameReader()
        reader.feed(b"abc")
        assert len(reader._buf) == 3

    def test_feed_2_boundary_fill_completely(self):
        """P2 BOUNDARY: Feed exactly maxBufSize(4) into empty buffer."""
        reader = FrameReader()
        reader.feed(b"abcd")
        assert len(reader._buf) == 4

    def test_feed_3_boundary_partial_then_fill(self):
        """P3 BOUNDARY: Buffer partially full, feed to exactly full."""
        reader = FrameReader()
        reader.feed(b"ab")
        reader.feed(b"cd")
        assert len(reader._buf) == 4

    def test_feed_4_rejected_zero_bytes(self):
        """REJECTED ¬P1: bytesIn=0 (empty feed)."""
        reader = FrameReader()
        reader.feed(b"")
        assert len(reader._buf) == 0  # no-op

    def test_feed_5_single_byte(self):
        """P5 BOUNDARY: Feed minimum positive amount (1 byte)."""
        reader = FrameReader()
        reader.feed(b"x")
        assert len(reader._buf) == 1

    def test_feed_6_accumulates_without_drain(self):
        """P6: Multiple feeds without drain accumulate."""
        reader = FrameReader()
        reader.feed(b"a")
        reader.feed(b"b")
        reader.feed(b"c")
        assert len(reader._buf) == 3


# ---------------------------------------------------------------------------
# DrainMessages (5 partitions)
#
# Preconditions:
#   P1: bytesConsumed? ≤ maxBufSize
#   P2: bytesConsumed? ≤ bufSize
# Output:
#   drained! = pendingMsgs + bytesConsumed?
# ---------------------------------------------------------------------------


class TestDrainMessagesPartitions:
    """DrainMessages: 3 accepted, 2 rejected/boundary."""

    def test_drain_1_happy_path_complete_message(self):
        """P1: Drain a complete message -> buffer emptied."""
        reader = FrameReader()
        msg = PingMessage(ts=9.0)
        reader.feed(encode_message(msg))
        buf_before = len(reader._buf)
        assert buf_before > 0

        messages = reader.drain_typed()
        assert len(messages) == 1
        assert len(reader._buf) == 0

    def test_drain_2_partial_message_preserved(self):
        """P2 REJECTED-ish: Insufficient bytes for complete frame.
        bytesConsumed=0 because no complete message available."""
        reader = FrameReader()
        frame = encode_message(PingMessage(ts=9.0))
        reader.feed(frame[:3])  # partial header
        messages = reader.drain_typed()
        assert len(messages) == 0
        assert len(reader._buf) == 3  # nothing consumed

    def test_drain_3_multiple_messages(self):
        """P3: Buffer contains 2 complete messages."""
        reader = FrameReader()
        reader.feed(encode_message(PingMessage(ts=9.0)))
        reader.feed(encode_message(PingMessage(ts=1.0)))
        messages = reader.drain_typed()
        assert len(messages) == 2
        assert len(reader._buf) == 0

    def test_drain_4_boundary_message_plus_partial(self):
        """P4 BOUNDARY: Buffer has complete message + partial next."""
        reader = FrameReader()
        full_frame = encode_message(PingMessage(ts=9.0))
        partial = encode_message(PingMessage(ts=1.0))[:3]
        reader.feed(full_frame + partial)
        messages = reader.drain_typed()
        assert len(messages) == 1  # only complete one
        assert len(reader._buf) == 3  # partial remains

    def test_drain_5_empty_buffer(self):
        """P5: Drain empty buffer -> nothing drained."""
        reader = FrameReader()
        messages = reader.drain_typed()
        assert len(messages) == 0
        assert len(reader._buf) == 0


# ---------------------------------------------------------------------------
# Shutdown (2 partitions — no preconditions)
# ---------------------------------------------------------------------------


class TestShutdownPartitions:
    """Shutdown: 2 accepted, 0 rejected."""

    def test_shutdown_1_with_clients_and_scene(self):
        """P1: Shutdown server with active clients and scene."""
        server = _server()
        _register(server, _sock(fd=10))
        _register(server, _sock(fd=20))
        _inject_scene(server, _scene_with("s1", TextElement(id="t1", content="A")))
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="t1", action="click", ts=1.0)
        )
        # Simulate shutdown (partial — no socket/file cleanup)
        for client in list(server._socket_listener.clients):
            client.close()
        server._socket_listener.clients.clear()
        server._socket_listener._readers.clear()
        _clear_all_scenes(server)
        server._event_queue.clear()
        server._socket_listener._server_sock = None

        assert len(server._socket_listener.clients) == 0
        assert len(server._socket_listener._readers) == 0
        assert _scene_count(server) == 0
        assert len(server._event_queue) == 0
        assert server._socket_listener.server_sock is None

    def test_shutdown_2_empty_server(self):
        """P2: Shutdown already-empty server (idempotent)."""
        server = _server()
        server._socket_listener.clients.clear()
        server._socket_listener._readers.clear()
        _clear_all_scenes(server)
        server._event_queue.clear()
        server._socket_listener._server_sock = None

        assert len(server._socket_listener.clients) == 0
        assert _scene_count(server) == 0


# ---------------------------------------------------------------------------
# Cross-operation invariant partitions
# ---------------------------------------------------------------------------


class TestInvariantPartitions:
    """Partitions that specifically exercise state invariant boundaries."""

    def test_inv_i1_reader_client_bijection(self):
        """I1: readers = clients after connect/disconnect sequence."""
        server = _server()
        s1, s2 = _sock(fd=10), _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        ss = server._socket_listener
        assert set(ss._readers.keys()) == {s.fileno() for s in ss.clients}

        ss.remove_client(s1)
        assert set(ss._readers.keys()) == {s.fileno() for s in ss.clients}

    def test_inv_i6_elem_kinds_coverage(self):
        """I6: elemIds ⊆ dom elemKinds — all elements have a kind."""
        server = _server()
        sock = _sock()
        scene = _scene_with(
            "s1",
            TextElement(id="t1", content="A"),
            ButtonElement(id="b1", label="B"),
            SeparatorElement(id="sep1"),
        )
        server._handle_message(sock, scene)
        assert _scene_count(server) > 0
        elems = _scene(server, "s1").elements
        elem_ids = {e.id for e in elems if e.id}
        elem_with_kind = {e.id for e in elems if e.id and hasattr(e, "kind")}
        assert elem_ids <= elem_with_kind

    def test_inv_i7_events_reference_scene_elements(self):
        """I7: hasScene=ztrue ⟹ eventQueue ⊆ elemIds.
        After receiving a scene with button, queueing an event should
        reference an element that exists in the scene."""
        server = _server()
        sock = _sock()
        scene = _scene_with("s1", ButtonElement(id="b1", label="X"))
        server._handle_message(sock, scene)
        assert _scene_count(server) > 0
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="b1", ts=1.0)
        )
        s1_elems = _scene(server, "s1").elements
        scene_elem_ids = {e.id for e in s1_elems if e.id}
        event_elem_ids = {e.element_id for e in server._event_queue}
        assert event_elem_ids <= scene_elem_ids

    def test_inv_i7_same_id_replace_drains_stale_events(self):
        """I7: Same-ID scene replace drains events for removed elements."""
        server = _server()
        sock = _sock()
        server._handle_message(
            sock, _scene_with("s1", ButtonElement(id="b1", label="Old"))
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="b1", ts=1.0)
        )
        # Replace s1 with new content that lacks b1
        server._handle_message(
            sock, _scene_with("s1", TextElement(id="t1", content="New"))
        )
        # b1 event drained — new scene has no b1
        assert len(server._event_queue) == 0


# ---------------------------------------------------------------------------
# Frame operations (workspace model)
# ---------------------------------------------------------------------------


def _framed_scene(
    scene_id: str,
    frame_id: str,
    *elems: TextElement | ButtonElement | SeparatorElement,
    frame_title: str | None = None,
    frame_size: tuple[int, int] | None = None,
    frame_flags: dict[str, bool] | None = None,
    frame_layout: Literal["tab", "stack"] | None = None,
) -> SceneMessage:
    # A framed scene always carries content: an empty element list is the Hub's
    # blank-on-removal signal, so default to one element when a caller gives none
    # (these frame-lifecycle tests exercise a populated frame, not a removal).
    return SceneMessage(
        id=scene_id,
        elements=list(elems) or [TextElement(id=f"{scene_id}-t", content="x")],
        frame_id=frame_id,
        frame_title=frame_title,
        frame_size=frame_size,
        frame_flags=frame_flags,
        frame_layout=frame_layout,
    )


class TestCreateFramePartitions:
    """CreateFrame: scene with frame_id creates a new frame."""

    def test_create_frame_happy_path(self):
        """New frame created with one scene."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        msg = _framed_scene("s1", "frame-beads", TextElement(id="t1", content="A"))
        server._handle_message(sock, msg)

        assert "frame-beads" in server._scenes.frames
        frame = server._scenes.frames["frame-beads"]
        assert frame.owner_fds == {10}
        assert frame.title == "frame-beads"
        assert "s1" in frame.scenes
        assert frame.scene_order == ["s1"]
        assert frame.active_tab == "s1"
        assert server._scenes.scene_to_frame["s1"] == "frame-beads"
        # The scene resolves through its frame — the only place scenes now live.
        assert server._scenes.resolve_scene("s1") is not None

    def test_create_frame_with_title(self):
        """Frame title comes from frame_title field."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        msg = _framed_scene(
            "s1",
            "frame-beads",
            TextElement(id="t1", content="A"),
            frame_title="Beads Explorer",
        )
        server._handle_message(sock, msg)

        assert server._scenes.frames["frame-beads"].title == "Beads Explorer"

    def test_add_scene_to_existing_frame(self):
        """Second scene added to same frame creates a tab."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._handle_message(
            sock, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        frame = server._scenes.frames["f1"]
        assert len(frame.scenes) == 2
        assert frame.scene_order == ["s1", "s2"]
        # F2: the tab is a user-owned selection. A second scene joins the strip
        # without pulling the user off what they were reading.
        assert frame.active_tab == "s1"
        assert server._scenes.scene_to_frame["s1"] == "f1"
        assert server._scenes.scene_to_frame["s2"] == "f1"

    def test_replace_scene_in_frame(self):
        """Replacing a scene in a frame drains stale events."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock,
            _framed_scene("s1", "f1", ButtonElement(id="b1", label="Old")),
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="clicked", ts=1.0)
        )
        server._handle_message(
            sock,
            _framed_scene("s1", "f1", TextElement(id="t1", content="New")),
        )

        assert len(server._event_queue) == 0
        assert server._scenes.frames["f1"].scenes["s1"].elements[0].id == "t1"


class TestFrameCascadePartitions:
    """Frame cascade: new frames get incrementing cascade indices."""

    def test_cascade_index_increments(self):
        """Each new frame gets a higher cascade index."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock

        server._handle_scene(sock, _framed_scene("s1", "f1"))
        server._handle_scene(sock, _framed_scene("s2", "f2"))
        server._handle_scene(sock, _framed_scene("s3", "f3"))

        assert server._scenes.frames["f1"].cascade_index == 0
        assert server._scenes.frames["f2"].cascade_index == 1
        assert server._scenes.frames["f3"].cascade_index == 2

    def test_cascade_index_reuses_after_disposal(self):
        """Disposing a frame frees its index for reuse by the next frame.

        A *closed* frame keeps its index, along with everything else about it —
        it is still there, waiting to be asked for.
        """
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock

        server._handle_scene(sock, _framed_scene("s1", "f1"))
        server._handle_scene(sock, _framed_scene("s2", "f2"))
        server._scenes.dispose_frame("f1")

        # After disposing f1 (index 0), f2 keeps index 1, so f3 gets index 0
        server._handle_scene(sock, _framed_scene("s3", "f3"))
        assert server._scenes.frames["f3"].cascade_index == 0


class TestConnectMessagePartitions:
    """ConnectMessage: client identifies itself with a display name."""

    def test_identify_sets_name(self):
        """ConnectMessage stores the client's display name."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock

        server._handle_connect(sock, ConnectMessage(name="quarry", kind="test"))

        assert server.client_name(10) == "quarry"

    def test_identify_updates_name(self):
        """Sending ConnectMessage again updates the name (idempotent)."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock

        server._handle_connect(sock, ConnectMessage(name="quarry", kind="test"))
        server._handle_connect(sock, ConnectMessage(name="biff", kind="test"))

        assert server.client_name(10) == "biff"

    def test_disconnect_clears_name(self):
        """Disconnecting a client removes its name."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock

        server._handle_connect(sock, ConnectMessage(name="quarry", kind="test"))
        server._socket_listener.remove_client(sock)

        assert server.client_name(10) is None

    def test_unnamed_client_returns_none(self):
        """A client that never sent ConnectMessage has no name."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock

        assert server.client_name(10) is None


class TestDisposeFramePartitions:
    """DisposeFrame: the content half — the frame and all its scenes go."""

    def test_dispose_frame_removes_scenes(self):
        """Disposing a frame removes all its scenes and widget state."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock
        server._handle_message(
            sock, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._handle_message(
            sock, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        server._scenes.dispose_frame("f1")

        assert "f1" not in server._scenes.frames
        assert "s1" not in server._scenes.scene_to_frame
        assert "s2" not in server._scenes.scene_to_frame
        assert server._scenes.widget_state_for("s1") is None
        assert server._scenes.widget_state_for("s2") is None

    def test_dispose_nonexistent_frame_is_noop(self):
        """Disposing a frame that doesn't exist is idempotent."""
        server = _server()
        server._scenes.dispose_frame("nonexistent")
        assert len(server._event_queue) == 0

    def test_user_close_keeps_the_frame_and_everything_in_it(self):
        """The visibility half, beside the content one — the whole of the split."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock
        server._handle_message(
            sock, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )

        server._close_frame("f1")

        assert server._scenes.frames["f1"].is_closed is True
        assert server._scenes.scene_to_frame["s1"] == "f1"
        assert server._scenes.widget_state_for("s1") is not None

    def test_close_nonexistent_frame_is_noop(self):
        """Closing a frame that isn't up is an answer, not an error."""
        server = _server()
        server._close_frame("nonexistent")
        assert len(server._event_queue) == 0


class TestDisconnectFrameCleanupPartitions:
    """DisconnectClient: orphans scenes instead of removing them."""

    def test_disconnect_transfers_client_scenes(self):
        """Disconnecting a client transfers its scenes to remaining client."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._handle_message(
            s2, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        server._socket_listener.remove_client(s1)

        # Frame persists — s1 transferred to remaining client (fd=20)
        assert "f1" in server._scenes.frames
        frame = server._scenes.frames["f1"]
        assert "s1" in frame.scenes
        assert "s2" in frame.scenes
        assert frame.owner_fds == {20}
        assert server._scenes.scene_to_owner["s1"] == 20

    def test_disconnect_sole_owner_removes_frame(self):
        """Disconnecting the only client orphans the frame, not removes it."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )

        server._socket_listener.remove_client(sock)

        assert "f1" in server._scenes.frames
        assert server._scenes.scene_to_owner["s1"] == _ORPHAN_FD

    def test_disconnect_preserves_other_frames(self):
        """Disconnecting a client orphans its frame; other frames unaffected."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._handle_message(
            s2, _framed_scene("s2", "f2", TextElement(id="t2", content="B"))
        )

        server._socket_listener.remove_client(s1)

        assert "f1" in server._scenes.frames
        assert "f2" in server._scenes.frames
        assert server._scenes.frames["f2"].owner_fds == {20}

    def test_disconnect_with_no_frames_is_clean(self):
        """Disconnecting a client with no frames is clean."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)

        server._socket_listener.remove_client(sock)

        assert len(server._scenes.frames) == 0

    def test_ephemeral_client_scene_persists(self):
        """One client sends a framed scene and disconnects — scene persists."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )

        server._socket_listener.remove_client(sock)

        assert "f1" in server._scenes.frames
        frame = server._scenes.frames["f1"]
        assert "s1" in frame.scenes
        assert server._scenes.scene_to_owner["s1"] == _ORPHAN_FD

    def test_orphaned_frame_closeable_by_user(self):
        """An orphaned frame can be put away by the user like any other."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._socket_listener.remove_client(sock)
        assert "f1" in server._scenes.frames

        server._close_frame("f1")

        assert server._scenes.frames["f1"].is_closed is True

    def test_new_client_adopts_orphaned_frame(self):
        """After a frame is orphaned, a new client can adopt it."""
        server = _server()
        s1 = _sock(fd=10)
        _register(server, s1)
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._socket_listener.remove_client(s1)
        assert "f1" in server._scenes.frames

        s2 = _sock(fd=20)
        _register(server, s2)
        server._handle_message(
            s2, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        frame = server._scenes.frames["f1"]
        assert 20 in frame.owner_fds

    def test_ownership_transfers_on_disconnect(self):
        """Two clients in a frame; disconnect transfers scenes to survivor."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._handle_message(
            s2, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        server._socket_listener.remove_client(s1)

        assert server._scenes.scene_to_owner["s1"] == 20
        assert server._scenes.scene_to_owner["s2"] == 20


class TestFrameOwnershipPartitions:
    """Frame ownership: multiple clients can contribute to the same frame."""

    def test_second_client_contributes_to_frame(self):
        """A different client can add scenes to any frame."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )

        server._handle_message(
            s2, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        frame = server._scenes.frames["f1"]
        assert len(frame.scenes) == 2
        assert "s1" in frame.scenes
        assert "s2" in frame.scenes
        assert frame.owner_fds == {10, 20}

    def test_scene_to_owner_tracks_contributing_client(self):
        """Each scene tracks which client contributed it."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._handle_message(
            s2, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        assert server._scenes.scene_to_owner["s1"] == 10
        assert server._scenes.scene_to_owner["s2"] == 20


class TestFrameStaleEventDrainPartitions:
    """Closing a frame drops this Display's queued interactions for its elements."""

    def test_close_frame_drains_events(self):
        """X6 — a button in a window the user just shut must not fire afterwards."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock
        server._handle_message(
            sock,
            _framed_scene("s1", "f1", ButtonElement(id="b1", label="X")),
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="clicked", ts=1.0, scene_id="s1"
            )
        )

        server._close_frame("f1")

        # b1 event drained
        remaining = [e for e in server._event_queue if e.element_id == "b1"]
        assert len(remaining) == 0

    def test_close_frame_leaves_a_shared_id_alone_in_a_frame_still_up(self):
        """The drain is scoped by scene, because element ids are not unique.

        Two frames can each hold a button called ``save``. Draining by element id
        would cancel the click the user is waiting on in the frame that is still
        painted --- the same reason the stale path subtracts its survivors.
        """
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._socket_listener._fd_to_client[10] = sock
        server._handle_message(
            sock, _framed_scene("s1", "f1", ButtonElement(id="save", label="Save"))
        )
        server._handle_message(
            sock, _framed_scene("s2", "f2", ButtonElement(id="save", label="Save"))
        )
        for scene_id in ("s1", "s2"):
            server._event_queue.append(
                RemoteEventHandlerInvocation(
                    element_id="save", action="clicked", ts=1.0, scene_id=scene_id
                )
            )

        server._close_frame("f1")

        surviving = [(e.element_id, e.scene_id) for e in server._event_queue]
        assert surviving == [("save", "s2")]

    def test_close_frame_leaves_a_menu_click_alone(self):
        """A menu-bar click carries no scene, so it belongs to no frame."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock, _framed_scene("s1", "f1", ButtonElement(id="b1", label="X"))
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="leaf", action="menu", ts=1.0)
        )

        server._close_frame("f1")

        assert [e.action for e in server._event_queue] == ["menu"]


class TestNoPushEverTakesFocus:
    """A push is a notification, not a window-raise — over the whole cross product."""

    def test_a_new_frames_scene_asks_for_no_focus(self):
        """N1 — being born on screen is not a raise."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        assert server._scenes.consume_focus("f1") is False

    def test_a_new_scene_leaves_a_docked_frame_docked(self):
        """N3 — the partition that used to assert the opposite."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._scenes.minimize("f1")
        server._handle_message(sock, _framed_scene("s2", "f1"))
        assert server._scenes.frames["f1"].is_docked is True
        assert server._scenes.consume_focus("f1") is False

    def test_a_new_scene_leaves_a_closed_frame_closed(self):
        """N4 — a second board arriving does not reopen the window the user shut."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._close_frame("f1")
        server._handle_message(sock, _framed_scene("s2", "f1"))
        assert server._scenes.frames["f1"].is_closed is True

    def test_repushed_scene_leaves_a_docked_frame_docked(self):
        """R2 — replacing a scene repaints in place: a frame put away stays away."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._scenes.minimize("f1")
        server._handle_message(sock, _framed_scene("s1", "f1"))
        assert server._scenes.frames["f1"].is_docked is True

    def test_repushed_scene_leaves_a_closed_frame_closed(self):
        """R3 — bug B, through the socket path the user actually meets it on."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._close_frame("f1")
        server._handle_message(sock, _framed_scene("s1", "f1"))
        assert server._scenes.frames["f1"].is_closed is True

    def test_close_frame_clears_focus(self):
        """X7 — a frame that is not painted cannot take focus."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._scenes.request_focus("f1")
        server._close_frame("f1")
        assert server._scenes.consume_focus("f1") is False

    def test_close_other_frame_preserves_focus(self):
        """Closing a different frame leaves the focus request standing."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._handle_message(sock, _framed_scene("s2", "f2"))
        server._scenes.request_focus("f2")
        server._close_frame("f1")
        assert server._scenes.consume_focus("f2") is True


class TestFrameSizeAndFlagsPartitions:
    """Frame size and flags: initial dimensions and ImGui window flags."""

    def test_frame_size_stored(self):
        """frame_size from SceneMessage is stored on the _Frame."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(sock, _framed_scene("s1", "f1", frame_size=(400, 200)))
        assert server._scenes.frames["f1"].initial_size == (400, 200)

    def test_frame_size_none_by_default(self):
        """Frames without frame_size have initial_size=None."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(sock, _framed_scene("s1", "f1"))
        assert server._scenes.frames["f1"].initial_size is None

    def test_frame_flags_stored(self):
        """frame_flags from SceneMessage are stored on the _Frame."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        flags = {"no_resize": True, "auto_resize": False}
        server._handle_scene(sock, _framed_scene("s1", "f1", frame_flags=flags))
        assert server._scenes.frames["f1"].flags == flags

    def test_frame_flags_none_by_default(self):
        """Frames without frame_flags have flags=None."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(sock, _framed_scene("s1", "f1"))
        assert server._scenes.frames["f1"].flags is None

    def test_frame_size_only_set_on_creation(self):
        """Subsequent scenes to the same frame don't overwrite initial_size."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(sock, _framed_scene("s1", "f1", frame_size=(400, 200)))
        server._handle_scene(sock, _framed_scene("s2", "f1", frame_size=(800, 600)))
        # initial_size is set at frame creation time, not updated
        assert server._scenes.frames["f1"].initial_size == (400, 200)

    def test_frame_flags_update_on_subsequent_scene(self):
        """Subsequent scenes to the same frame update flags."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(
            sock, _framed_scene("s1", "f1", frame_flags={"no_resize": True})
        )
        assert server._scenes.frames["f1"].flags == {"no_resize": True}
        server._handle_scene(
            sock,
            _framed_scene("s2", "f1", frame_flags={"auto_resize": True}),
        )
        assert server._scenes.frames["f1"].flags == {"auto_resize": True}

    def test_frame_flags_unchanged_when_not_provided(self):
        """Subsequent scenes without frame_flags preserve existing flags."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(
            sock, _framed_scene("s1", "f1", frame_flags={"no_resize": True})
        )
        server._handle_scene(sock, _framed_scene("s2", "f1"))
        assert server._scenes.frames["f1"].flags == {"no_resize": True}


class TestFrameLayoutPartitions:
    """Frame layout: tab vs stack rendering mode."""

    def test_default_layout_is_tab(self):
        """Frames default to tab layout."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(sock, _framed_scene("s1", "f1"))
        assert server._scenes.frames["f1"].layout == "tab"

    def test_stack_layout_on_creation(self):
        """frame_layout='stack' sets layout on frame creation."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(sock, _framed_scene("s1", "f1", frame_layout="stack"))
        assert server._scenes.frames["f1"].layout == "stack"

    def test_layout_updated_by_subsequent_scene(self):
        """Subsequent scene with frame_layout updates the frame layout."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(sock, _framed_scene("s1", "f1", frame_layout="tab"))
        server._handle_scene(sock, _framed_scene("s2", "f1", frame_layout="stack"))
        assert server._scenes.frames["f1"].layout == "stack"

    def test_layout_unchanged_when_not_provided(self):
        """Subsequent scene without frame_layout preserves existing layout."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_scene(sock, _framed_scene("s1", "f1", frame_layout="stack"))
        server._handle_scene(sock, _framed_scene("s2", "f1"))
        assert server._scenes.frames["f1"].layout == "stack"

    def test_frame_layout_in_protocol_round_trip(self):
        """frame_layout survives serialization and deserialization."""
        from punt_lux.protocol import message_from_dict, message_to_dict

        msg = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="Hello")],
            frame_id="f1",
            frame_layout="stack",
        )
        d = message_to_dict(msg)
        assert d["frame_layout"] == "stack"
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert restored.frame_layout == "stack"

    def test_frame_layout_none_omitted_in_protocol(self):
        """frame_layout=None is stripped from serialized dict."""
        from punt_lux.protocol import message_to_dict

        msg = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="Hello")],
            frame_id="f1",
        )
        d = message_to_dict(msg)
        assert "frame_layout" not in d

    def test_invalid_frame_layout_deserialized_as_none(self):
        """Invalid frame_layout values in wire data are discarded."""
        from punt_lux.protocol import message_from_dict

        d = {
            "type": "scene",
            "id": "s1",
            "elements": [],
            "frame_id": "f1",
            "frame_layout": "bogus",
        }
        msg = message_from_dict(d)
        assert isinstance(msg, SceneMessage)
        assert msg.frame_layout is None

    def test_non_string_frame_layout_deserialized_as_none(self):
        """Non-string frame_layout values in wire data are discarded."""
        from punt_lux.protocol import message_from_dict

        d = {
            "type": "scene",
            "id": "s1",
            "elements": [],
            "frame_id": "f1",
            "frame_layout": 42,
        }
        msg = message_from_dict(d)
        assert isinstance(msg, SceneMessage)
        assert msg.frame_layout is None


class _TabBarClosingOneTab:
    """A stand-in imgui whose tab bar reports ``close_id``'s ✕ as clicked.

    Only what ``_render_frame_tabs`` calls. Every tab reports *not selected*, so
    the render branch (which needs a GL context) is never entered and the close
    branch — the one this change re-routed — is what runs.
    """

    def __init__(self, close_id: str) -> None:
        self._close_id = close_id

    def begin_tab_bar(self, _label: str) -> bool:
        return True

    def begin_tab_item(self, label: str, _closable: bool) -> tuple[bool, bool]:
        scene_id = label.split("##")[-1]
        return False, scene_id != self._close_id

    def end_tab_bar(self) -> None:
        return


class TestTabCloseDisposes:
    """D6 — the tab ✕ is a content dismissal, so an emptied frame is disposed.

    Not put away: the user said that *scene* is gone, and a frame with no
    content is a husk. This is the one call site of the old ``close_frame`` most
    easily mistaken for the frame ✕, and routing it to ``close`` would leave an
    empty window that no push could ever refill.
    """

    def test_closing_the_last_tab_disposes_the_frame(self):
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        frame = server._scenes.frames["f1"]

        server._render_frame_tabs(frame, _TabBarClosingOneTab("s1"))

        assert "f1" not in server._scenes.frames
        assert "s1" not in server._scenes.scene_to_frame

    def test_closing_one_tab_of_several_keeps_the_frame(self):
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        for sid in ("s1", "s2"):
            server._handle_message(
                sock, _framed_scene(sid, "f1", TextElement(id=f"t-{sid}", content="A"))
            )
        frame = server._scenes.frames["f1"]

        server._render_frame_tabs(frame, _TabBarClosingOneTab("s1"))

        assert "f1" in server._scenes.frames
        assert server._scenes.resolve_scene("s1") is None
        assert server._scenes.resolve_scene("s2") is not None


class TestFrameVisibilityPartitions:
    """Where a frame is, and which gestures are entitled to move it."""

    def test_frame_starts_on_screen(self):
        """N1 — a frame is born on screen, and that is the whole birth policy."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        assert server._scenes.frames["f1"].is_on_screen is True

    def test_fit_all_undocks_every_docked_frame(self):
        """_apply_fit_all() brings the dock back on screen to be tiled."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._handle_message(sock, _framed_scene("s2", "f2"))
        server._scenes.minimize("f1")
        server._scenes.minimize("f2")
        server._fit_all_frames = True
        result = server._apply_fit_all()
        assert result is True
        assert server._scenes.frames["f1"].is_on_screen is True
        assert server._scenes.frames["f2"].is_on_screen is True

    def test_fit_all_leaves_a_closed_frame_closed(self):
        """V4 — fitting lays out what is on screen; it is not a way to reopen.

        Expand All and the Windows menu's closed list are the gestures that mean
        "bring it back"; a tiling command must not smuggle that in.
        """
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._handle_message(sock, _framed_scene("s2", "f2"))
        server._close_frame("f1")
        server._scenes.minimize("f2")
        server._fit_all_frames = True

        assert server._apply_fit_all() is True
        assert server._scenes.frames["f1"].is_closed is True
        assert server._scenes.frames["f2"].is_on_screen is True

    def test_fit_all_noop_when_not_requested(self):
        """_apply_fit_all() returns False when no fit was requested."""
        server = _server()
        assert server._apply_fit_all() is False

    def test_closing_a_docked_frame_closes_it_rather_than_removing_it(self):
        """X2 — closed is reachable from the dock, and it is still a visibility."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._scenes.minimize("f1")
        server._close_frame("f1")
        assert server._scenes.frames["f1"].is_closed is True
        assert server._scenes.docked_frames() == []

    def test_clear_all_disposes_every_frame_whatever_its_visibility(self):
        """D5 — Clear All means the content is gone, not that it was put away."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._handle_message(sock, _framed_scene("s2", "f2"))
        server._handle_message(sock, _framed_scene("s3", "f3"))
        server._close_frame("f1")
        server._scenes.minimize("f2")

        server._clear_all()

        assert len(server._scenes.frames) == 0
        assert len(server._scenes.scene_to_frame) == 0
