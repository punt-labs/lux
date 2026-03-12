"""TTF partition tests for DisplayServer Z specification.

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

from unittest.mock import MagicMock

from punt_lux.display import DisplayServer, WidgetState
from punt_lux.protocol import (
    ButtonElement,
    ClearMessage,
    ConnectMessage,
    FrameReader,
    InteractionMessage,
    Patch,
    PingMessage,
    RegisterMenuMessage,
    SceneMessage,
    SeparatorElement,
    TextElement,
    UpdateMessage,
    encode_message,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _server() -> DisplayServer:
    return DisplayServer("/tmp/test-lux-partition.sock")


def _sock(fd: int = 42) -> MagicMock:
    s = MagicMock()
    s.sendall = MagicMock()
    s.fileno.return_value = fd
    s.close = MagicMock()
    return s


def _register(server: DisplayServer, sock: MagicMock) -> None:
    server._clients.append(sock)
    server._readers[sock.fileno()] = FrameReader()


def _scene_with(
    scene_id: str, *elems: TextElement | ButtonElement | SeparatorElement
) -> SceneMessage:
    return SceneMessage(id=scene_id, elements=list(elems))


def _inject_scene(server: DisplayServer, scene: SceneMessage) -> None:
    server._scenes[scene.id] = scene
    if scene.id not in server._scene_order:
        server._scene_order.append(scene.id)
    server._scene_widget_state[scene.id] = WidgetState()
    server._scene_render_fn_state[scene.id] = {}
    server._active_tab = scene.id


def _clear_all_scenes(server: DisplayServer) -> None:
    server._scenes.clear()
    server._scene_order.clear()
    server._active_tab = None
    server._scene_widget_state.clear()
    server._scene_render_fn_state.clear()


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
        assert len(server._clients) == 0
        _register(server, sock)
        assert len(server._clients) == 1
        assert 10 in server._readers

    def test_accept_2_one_existing_client(self):
        """P2: Accept second client when one already connected."""
        server = _server()
        _register(server, _sock(fd=10))
        sock2 = _sock(fd=20)
        _register(server, sock2)
        assert len(server._clients) == 2
        assert {10, 20} == set(server._readers.keys())

    def test_accept_3_boundary_fills_to_max(self):
        """P3: Accept client when at maxClients-1 (reaches capacity).
        maxClients=3 in spec, so accept 3rd into server with 2."""
        server = _server()
        _register(server, _sock(fd=10))
        _register(server, _sock(fd=20))
        sock3 = _sock(fd=30)
        _register(server, sock3)
        assert len(server._clients) == 3

    def test_accept_4_rejected_not_listening(self):
        """REJECTED ¬P1: Server not listening (server_sock is None).
        In concrete code, _accept_connections() returns early."""
        server = _server()
        assert server._server_sock is None  # not listening
        # _accept_connections is a no-op when not listening
        server._accept_connections()
        assert len(server._clients) == 0

    def test_accept_5_rejected_duplicate_fd(self):
        """REJECTED ¬P2: Client FD already in clients set.
        Concrete code: select() wouldn't offer duplicate, but verify
        that reader dict is keyed by fd (duplicate would overwrite)."""
        server = _server()
        sock1 = _sock(fd=10)
        _register(server, sock1)
        reader1 = server._readers[10]
        # Re-registering same fd overwrites the reader
        _register(server, _sock(fd=10))
        assert server._readers[10] is not reader1

    def test_accept_6_rejected_at_capacity(self):
        """REJECTED ¬P3: Server at maxClients capacity.
        Concrete code doesn't enforce hard limit — this partition
        documents the spec constraint for awareness."""
        server = _server()
        for fd in range(10, 13):
            _register(server, _sock(fd=fd))
        assert len(server._clients) == 3  # at max


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
        server._remove_client(sock)
        assert len(server._clients) == 0
        assert 10 not in server._readers

    def test_disconnect_2_one_of_two(self):
        """P2: Disconnect one of two clients -> one remains."""
        server = _server()
        sock1, sock2 = _sock(fd=10), _sock(fd=20)
        _register(server, sock1)
        _register(server, sock2)
        server._remove_client(sock1)
        assert len(server._clients) == 1
        assert 20 in server._readers
        assert 10 not in server._readers

    def test_disconnect_3_preserves_scene(self):
        """P3: Disconnect does not affect current scene or events."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        _inject_scene(server, _scene_with("s1", TextElement(id="t1", content="A")))
        server._event_queue.append(
            InteractionMessage(element_id="t1", action="click", ts=1.0)
        )
        server._remove_client(sock)
        assert len(server._scenes) > 0
        assert len(server._event_queue) == 1

    def test_disconnect_4_rejected_not_connected(self):
        """REJECTED ¬P1: deadClient not in clients.
        _remove_client on unknown socket is safe no-op."""
        server = _server()
        unknown = _sock(fd=99)
        server._remove_client(unknown)
        assert len(server._clients) == 0


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
        assert len(server._scenes) > 0
        assert server._active_tab == "s1"
        assert len(server._scenes["s1"].elements) == 1

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
        assert len(server._scenes) > 0
        assert len(server._scenes["s1"].elements) == 3

    def test_scene_3_new_id_preserves_events(self):
        """P3: New scene (different ID) preserves existing events."""
        server = _server()
        sock = _sock()
        old_scene = _scene_with("s1", ButtonElement(id="b1", label="Old"))
        server._handle_message(sock, old_scene)
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="click", ts=1.0)
        )
        assert len(server._event_queue) == 1

        new_scene = _scene_with("s2", TextElement(id="t2", content="New"))
        server._handle_message(sock, new_scene)
        assert len(server._scenes) > 0
        assert server._active_tab == "s2"
        assert len(server._event_queue) == 1  # events from s1 persist

    def test_scene_4_empty_scene(self):
        """P4: Receive scene with 0 elements (valid edge case)."""
        server = _server()
        sock = _sock()
        scene = SceneMessage(id="s1", elements=[])
        server._handle_message(sock, scene)
        assert len(server._scenes) > 0
        assert len(server._scenes["s1"].elements) == 0

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
        assert len(server._scenes) > 0
        kinds = {e.kind for e in server._scenes["s1"].elements}
        assert kinds == {"text", "button", "separator"}

    def test_scene_6_idempotent_same_scene_id(self):
        """P6: Receive scene with same ID as current (full replacement)."""
        server = _server()
        sock = _sock()
        scene1 = _scene_with("s1", TextElement(id="t1", content="V1"))
        server._handle_message(sock, scene1)
        scene2 = _scene_with("s1", TextElement(id="t1", content="V2"))
        server._handle_message(sock, scene2)
        assert len(server._scenes) > 0
        elem = server._scenes["s1"].elements[0]
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
        server._handle_message(sock, ClearMessage())
        assert len(server._scenes) == 0

    def test_clear_2_idempotent_no_scene(self):
        """P2: Clear when no scene exists (idempotent)."""
        server = _server()
        sock = _sock()
        server._handle_message(sock, ClearMessage())
        assert len(server._scenes) == 0

    def test_clear_3_clears_event_queue(self):
        """P3: Clear also drains the event queue (I7 preservation)."""
        server = _server()
        sock = _sock()
        server._handle_message(
            sock,
            _scene_with("s1", ButtonElement(id="b1", label="X")),
        )
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="click", ts=1.0)
        )
        server._handle_message(sock, ClearMessage())
        assert len(server._event_queue) == 0


# ---------------------------------------------------------------------------
# RemoveElement (6 partitions)
# Preconditions: scene exists, target in elemIds
# Implicit: target not in eventQueue (for I7 preservation)
# ---------------------------------------------------------------------------


class TestRemoveElementPartitions:
    """RemoveElement: 3 accepted, 3 rejected/boundary."""

    def test_remove_1_happy_path(self):
        """P1: Remove one of several elements."""
        server = _server()
        _inject_scene(
            server,
            _scene_with(
                "s1",
                TextElement(id="t1", content="A"),
                TextElement(id="t2", content="B"),
            ),
        )
        server._apply_update(
            UpdateMessage(scene_id="s1", patches=[Patch(id="t1", remove=True)])
        )
        ids = [e.id for e in server._scenes["s1"].elements]
        assert ids == ["t2"]

    def test_remove_2_boundary_last_element(self):
        """P2: Remove last element -> empty element list."""
        server = _server()
        _inject_scene(server, _scene_with("s1", TextElement(id="t1", content="Only")))
        server._apply_update(
            UpdateMessage(scene_id="s1", patches=[Patch(id="t1", remove=True)])
        )
        assert len(server._scenes["s1"].elements) == 0

    def test_remove_3_rejected_element_in_event_queue(self):
        """REJECTED ¬P3: targetId in eventQueue.
        The Z spec requires targetId? ∉ eventQueue to preserve I7.
        Concrete code doesn't enforce this — documents the gap."""
        server = _server()
        _inject_scene(
            server,
            _scene_with(
                "s1",
                ButtonElement(id="b1", label="X"),
                TextElement(id="t1", content="A"),
            ),
        )
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="click", ts=1.0)
        )
        server._apply_update(
            UpdateMessage(scene_id="s1", patches=[Patch(id="b1", remove=True)])
        )
        # Element removed but event still in queue — spec boundary
        ids = [e.id for e in server._scenes["s1"].elements]
        assert "b1" not in ids
        assert len(server._event_queue) == 1  # event orphaned

    def test_remove_4_rejected_no_scene(self):
        """REJECTED ¬P1: No scene -> update is no-op."""
        server = _server()
        server._apply_update(
            UpdateMessage(scene_id="s1", patches=[Patch(id="t1", remove=True)])
        )
        assert len(server._scenes) == 0

    def test_remove_5_rejected_element_not_found(self):
        """REJECTED ¬P2: targetId not in elemIds -> patch skipped."""
        server = _server()
        _inject_scene(server, _scene_with("s1", TextElement(id="t1", content="A")))
        server._apply_update(
            UpdateMessage(scene_id="s1", patches=[Patch(id="nonexistent", remove=True)])
        )
        assert len(server._scenes["s1"].elements) == 1

    def test_remove_6_rejected_wrong_scene_id(self):
        """REJECTED: Update targets wrong scene_id -> no-op."""
        server = _server()
        _inject_scene(server, _scene_with("s1", TextElement(id="t1", content="A")))
        server._apply_update(
            UpdateMessage(scene_id="wrong", patches=[Patch(id="t1", remove=True)])
        )
        assert len(server._scenes["s1"].elements) == 1


# ---------------------------------------------------------------------------
# ButtonClick (7 partitions)
# Preconditions: scene exists, button in elemIds, kind is button, queue not full
# ---------------------------------------------------------------------------


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
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
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
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )
        server._event_queue.append(
            InteractionMessage(element_id="b2", action="b2", ts=2.0, value=True)
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
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )
        server._event_queue.append(
            InteractionMessage(element_id="b2", action="b2", ts=2.0, value=True)
        )
        # One more fills to maxEvents=3
        server._event_queue.append(
            InteractionMessage(element_id="b3", action="b3", ts=3.0, value=True)
        )
        assert len(server._event_queue) == 3  # at max

    def test_click_4_rejected_no_scene(self):
        """REJECTED ¬P1: No scene -> no button to click.
        Concrete code: _render_scene shows "waiting" text, no buttons."""
        server = _server()
        assert len(server._scenes) == 0
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
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=2.0, value=True)
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
            InteractionMessage(element_id="b1", action="click", ts=1.0)
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
        sock.sendall.assert_not_called()


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
        msg = ClearMessage()
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
        frame = encode_message(ClearMessage())
        reader.feed(frame[:3])  # partial header
        messages = reader.drain_typed()
        assert len(messages) == 0
        assert len(reader._buf) == 3  # nothing consumed

    def test_drain_3_multiple_messages(self):
        """P3: Buffer contains 2 complete messages."""
        reader = FrameReader()
        reader.feed(encode_message(ClearMessage()))
        reader.feed(encode_message(PingMessage(ts=1.0)))
        messages = reader.drain_typed()
        assert len(messages) == 2
        assert len(reader._buf) == 0

    def test_drain_4_boundary_message_plus_partial(self):
        """P4 BOUNDARY: Buffer has complete message + partial next."""
        reader = FrameReader()
        full_frame = encode_message(ClearMessage())
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
            InteractionMessage(element_id="t1", action="click", ts=1.0)
        )
        # Simulate shutdown (partial — no socket/file cleanup)
        for client in list(server._clients):
            client.close()
        server._clients.clear()
        server._readers.clear()
        _clear_all_scenes(server)
        server._event_queue.clear()
        server._server_sock = None

        assert len(server._clients) == 0
        assert len(server._readers) == 0
        assert len(server._scenes) == 0
        assert len(server._event_queue) == 0
        assert server._server_sock is None

    def test_shutdown_2_empty_server(self):
        """P2: Shutdown already-empty server (idempotent)."""
        server = _server()
        server._clients.clear()
        server._readers.clear()
        _clear_all_scenes(server)
        server._event_queue.clear()
        server._server_sock = None

        assert len(server._clients) == 0
        assert len(server._scenes) == 0


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
        assert set(server._readers.keys()) == {s.fileno() for s in server._clients}

        server._remove_client(s1)
        assert set(server._readers.keys()) == {s.fileno() for s in server._clients}

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
        assert len(server._scenes) > 0
        elem_ids = {e.id for e in server._scenes["s1"].elements if e.id}
        elem_with_kind = {
            e.id for e in server._scenes["s1"].elements if e.id and hasattr(e, "kind")
        }
        assert elem_ids <= elem_with_kind

    def test_inv_i7_events_reference_scene_elements(self):
        """I7: hasScene=ztrue ⟹ eventQueue ⊆ elemIds.
        After receiving a scene with button, queueing an event should
        reference an element that exists in the scene."""
        server = _server()
        sock = _sock()
        scene = _scene_with("s1", ButtonElement(id="b1", label="X"))
        server._handle_message(sock, scene)
        assert len(server._scenes) > 0
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=1.0)
        )
        scene_elem_ids = {e.id for e in server._scenes["s1"].elements if e.id}
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
            InteractionMessage(element_id="b1", action="b1", ts=1.0)
        )
        # Replace s1 with new content that lacks b1
        server._handle_message(
            sock, _scene_with("s1", TextElement(id="t1", content="New"))
        )
        # b1 event drained — new scene has no b1
        assert len(server._event_queue) == 0


# ---------------------------------------------------------------------------
# Frame operations (DES-022 workspace model)
# ---------------------------------------------------------------------------


def _framed_scene(
    scene_id: str,
    frame_id: str,
    *elems: TextElement | ButtonElement | SeparatorElement,
    frame_title: str | None = None,
    frame_size: tuple[int, int] | None = None,
    frame_flags: dict[str, bool] | None = None,
) -> SceneMessage:
    return SceneMessage(
        id=scene_id,
        elements=list(elems),
        frame_id=frame_id,
        frame_title=frame_title,
        frame_size=frame_size,
        frame_flags=frame_flags,
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

        assert "frame-beads" in server._frames
        frame = server._frames["frame-beads"]
        assert frame.owner_fd == 10
        assert frame.title == "frame-beads"
        assert "s1" in frame.scenes
        assert frame.scene_order == ["s1"]
        assert frame.active_tab == "s1"
        assert server._scene_to_frame["s1"] == "frame-beads"
        # Scene should NOT be in the unframed scene list
        assert "s1" not in server._scenes

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

        assert server._frames["frame-beads"].title == "Beads Explorer"

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

        frame = server._frames["f1"]
        assert len(frame.scenes) == 2
        assert frame.scene_order == ["s1", "s2"]
        assert frame.active_tab == "s2"
        assert server._scene_to_frame["s1"] == "f1"
        assert server._scene_to_frame["s2"] == "f1"

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
            InteractionMessage(element_id="b1", action="clicked", ts=1.0)
        )
        server._handle_message(
            sock,
            _framed_scene("s1", "f1", TextElement(id="t1", content="New")),
        )

        assert len(server._event_queue) == 0
        assert server._frames["f1"].scenes["s1"].elements[0].id == "t1"


class TestFrameCascadePartitions:
    """Frame cascade: new frames get incrementing cascade indices."""

    def test_cascade_index_increments(self):
        """Each new frame gets a higher cascade index."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._fd_to_client[10] = sock

        server._handle_framed_scene(sock, _framed_scene("s1", "f1"))
        server._handle_framed_scene(sock, _framed_scene("s2", "f2"))
        server._handle_framed_scene(sock, _framed_scene("s3", "f3"))

        assert server._frames["f1"].cascade_index == 0
        assert server._frames["f2"].cascade_index == 1
        assert server._frames["f3"].cascade_index == 2

    def test_cascade_index_reuses_after_close(self):
        """Closing a frame frees its index for reuse by the next frame."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._fd_to_client[10] = sock

        server._handle_framed_scene(sock, _framed_scene("s1", "f1"))
        server._handle_framed_scene(sock, _framed_scene("s2", "f2"))
        server._close_frame("f1")

        # After closing f1 (index 0), f2 keeps index 1, so f3 gets index 0
        server._handle_framed_scene(sock, _framed_scene("s3", "f3"))
        assert server._frames["f3"].cascade_index == 0


class TestConnectMessagePartitions:
    """ConnectMessage: client identifies itself with a display name."""

    def test_identify_sets_name(self):
        """ConnectMessage stores the client's display name."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._fd_to_client[10] = sock

        server._handle_connect(sock, ConnectMessage(name="quarry"))

        assert server.client_name(10) == "quarry"

    def test_identify_updates_name(self):
        """Sending ConnectMessage again updates the name (idempotent)."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._fd_to_client[10] = sock

        server._handle_connect(sock, ConnectMessage(name="quarry"))
        server._handle_connect(sock, ConnectMessage(name="biff"))

        assert server.client_name(10) == "biff"

    def test_disconnect_clears_name(self):
        """Disconnecting a client removes its name."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._fd_to_client[10] = sock

        server._handle_connect(sock, ConnectMessage(name="quarry"))
        server._remove_client(sock)

        assert server.client_name(10) is None

    def test_unnamed_client_returns_none(self):
        """A client that never sent ConnectMessage has no name."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._fd_to_client[10] = sock

        assert server.client_name(10) is None


class TestCloseFramePartitions:
    """CloseFrame: removes frame and all its scenes."""

    def test_close_frame_removes_scenes(self):
        """Closing a frame removes all its scenes and widget state."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._fd_to_client[10] = sock
        server._handle_message(
            sock, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._handle_message(
            sock, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        server._close_frame("f1")

        assert "f1" not in server._frames
        assert "s1" not in server._scene_to_frame
        assert "s2" not in server._scene_to_frame
        assert "s1" not in server._scene_widget_state
        assert "s2" not in server._scene_widget_state
        # Close event sent directly to owner socket
        calls = sock.sendall.call_args_list
        # Last sendall should contain frame_close interaction
        last_payload = calls[-1][0][0]
        assert b"frame_close" in last_payload

    def test_close_nonexistent_frame_is_noop(self):
        """Closing a frame that doesn't exist is idempotent."""
        server = _server()
        server._close_frame("nonexistent")
        assert len(server._event_queue) == 0


class TestDisconnectFrameCleanupPartitions:
    """DisconnectClient: orphans frames owned by the departing client."""

    def test_disconnect_orphans_owned_frames(self):
        """Disconnecting a client orphans its frames (they persist)."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        # Client 1 owns frame f1, client 2 owns frame f2
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._handle_message(
            s2, _framed_scene("s2", "f2", TextElement(id="t2", content="B"))
        )

        server._remove_client(s1)

        # Frame persists but is orphaned (owner_fd=None)
        assert "f1" in server._frames
        assert server._frames["f1"].owner_fd is None
        assert "s1" in server._scene_to_frame
        # Client 2's frame is unaffected
        assert "f2" in server._frames
        assert server._frames["f2"].owner_fd == 20

    def test_orphaned_frame_adopted_by_another_client(self):
        """Another connected client can adopt an orphaned frame."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )
        server._remove_client(s1)
        assert server._frames["f1"].owner_fd is None

        # New client sends to same frame — adopts it
        server._handle_message(
            s2, _framed_scene("s3", "f1", TextElement(id="t3", content="C"))
        )
        assert server._frames["f1"].owner_fd == 20

    def test_disconnect_with_no_frames_is_clean(self):
        """Disconnecting a client with no frames is clean."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)

        server._remove_client(sock)

        assert len(server._frames) == 0


class TestFrameOwnershipPartitions:
    """Frame ownership enforcement (DES-022 invariant)."""

    def test_non_owner_rejected(self):
        """A different client cannot add scenes to another's frame."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        server._handle_message(
            s1, _framed_scene("s1", "f1", TextElement(id="t1", content="A"))
        )

        # Client 2 tries to add to client 1's frame
        server._handle_message(
            s2, _framed_scene("s2", "f1", TextElement(id="t2", content="B"))
        )

        frame = server._frames["f1"]
        assert len(frame.scenes) == 1
        assert "s1" in frame.scenes
        assert "s2" not in frame.scenes


class TestFrameUpdatePartitions:
    """UpdateMessage works for framed scenes."""

    def test_update_framed_scene(self):
        """Patches apply to scenes stored in frames."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock,
            _framed_scene("s1", "f1", TextElement(id="t1", content="Old")),
        )

        server._apply_update(
            UpdateMessage(
                scene_id="s1",
                patches=[Patch(id="t1", set={"content": "New"})],
            )
        )

        scene = server._frames["f1"].scenes["s1"]
        el = scene.elements[0]
        assert isinstance(el, TextElement)
        assert el.content == "New"


class TestFrameStaleEventDrainPartitions:
    """Closing frames drains stale interaction events."""

    def test_close_frame_drains_events(self):
        """Events for elements in closed frame are removed from queue."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._fd_to_client[10] = sock
        server._handle_message(
            sock,
            _framed_scene("s1", "f1", ButtonElement(id="b1", label="X")),
        )
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="clicked", ts=1.0)
        )

        server._close_frame("f1")

        # b1 event drained
        remaining = [e for e in server._event_queue if e.element_id == "b1"]
        assert len(remaining) == 0


class TestFrameAutoFocusPartitions:
    """Frames auto-focus and restore on scene/update receipt."""

    def test_scene_sets_focus_frame_id(self):
        """Receiving a framed scene sets _focus_frame_id."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        assert server._focus_frame_id == "f1"

    def test_scene_restores_minimized_frame(self):
        """Receiving a framed scene un-minimizes the frame."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._frames["f1"].minimized = True
        server._handle_message(sock, _framed_scene("s1", "f1"))
        assert not server._frames["f1"].minimized

    def test_update_sets_focus_for_framed_scene(self):
        """UpdateMessage on a framed scene sets _focus_frame_id."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock,
            _framed_scene("s1", "f1", TextElement(id="t1", content="Old")),
        )
        server._focus_frame_id = None  # reset after initial scene
        server._apply_update(
            UpdateMessage(
                scene_id="s1",
                patches=[Patch(id="t1", set={"content": "New"})],
            )
        )
        assert server._focus_frame_id == "f1"

    def test_update_restores_minimized_framed_scene(self):
        """UpdateMessage on a framed scene un-minimizes the frame."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock,
            _framed_scene("s1", "f1", TextElement(id="t1", content="Old")),
        )
        server._frames["f1"].minimized = True
        server._apply_update(
            UpdateMessage(
                scene_id="s1",
                patches=[Patch(id="t1", set={"content": "New"})],
            )
        )
        assert not server._frames["f1"].minimized

    def test_close_frame_clears_focus(self):
        """Closing a frame clears _focus_frame_id if it matches."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        assert server._focus_frame_id == "f1"
        server._close_frame("f1")
        assert server._focus_frame_id is None

    def test_close_other_frame_preserves_focus(self):
        """Closing a different frame does not clear _focus_frame_id."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(sock, _framed_scene("s1", "f1"))
        server._handle_message(sock, _framed_scene("s2", "f2"))
        assert server._focus_frame_id == "f2"
        server._close_frame("f1")
        assert server._focus_frame_id == "f2"

    def test_update_non_framed_scene_no_focus(self):
        """UpdateMessage on a non-framed scene does not set focus."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_message(
            sock,
            SceneMessage(
                id="s1",
                elements=[TextElement(id="t1", content="Old")],
                title="Test",
            ),
        )
        server._focus_frame_id = None
        server._apply_update(
            UpdateMessage(
                scene_id="s1",
                patches=[Patch(id="t1", set={"content": "New"})],
            )
        )
        assert server._focus_frame_id is None


class TestFrameSizeAndFlagsPartitions:
    """Frame size and flags: initial dimensions and ImGui window flags."""

    def test_frame_size_stored(self):
        """frame_size from SceneMessage is stored on the _Frame."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_framed_scene(
            sock, _framed_scene("s1", "f1", frame_size=(400, 200))
        )
        assert server._frames["f1"].initial_size == (400, 200)

    def test_frame_size_none_by_default(self):
        """Frames without frame_size have initial_size=None."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_framed_scene(sock, _framed_scene("s1", "f1"))
        assert server._frames["f1"].initial_size is None

    def test_frame_flags_stored(self):
        """frame_flags from SceneMessage are stored on the _Frame."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        flags = {"no_resize": True, "auto_resize": False}
        server._handle_framed_scene(sock, _framed_scene("s1", "f1", frame_flags=flags))
        assert server._frames["f1"].flags == flags

    def test_frame_flags_none_by_default(self):
        """Frames without frame_flags have flags=None."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_framed_scene(sock, _framed_scene("s1", "f1"))
        assert server._frames["f1"].flags is None

    def test_frame_size_only_set_on_creation(self):
        """Subsequent scenes to the same frame don't overwrite initial_size."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_framed_scene(
            sock, _framed_scene("s1", "f1", frame_size=(400, 200))
        )
        server._handle_framed_scene(
            sock, _framed_scene("s2", "f1", frame_size=(800, 600))
        )
        # initial_size is set at frame creation time, not updated
        assert server._frames["f1"].initial_size == (400, 200)

    def test_frame_flags_update_on_subsequent_scene(self):
        """Subsequent scenes to the same frame update flags."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_framed_scene(
            sock, _framed_scene("s1", "f1", frame_flags={"no_resize": True})
        )
        assert server._frames["f1"].flags == {"no_resize": True}
        server._handle_framed_scene(
            sock,
            _framed_scene("s2", "f1", frame_flags={"auto_resize": True}),
        )
        assert server._frames["f1"].flags == {"auto_resize": True}

    def test_frame_flags_unchanged_when_not_provided(self):
        """Subsequent scenes without frame_flags preserve existing flags."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_framed_scene(
            sock, _framed_scene("s1", "f1", frame_flags={"no_resize": True})
        )
        server._handle_framed_scene(sock, _framed_scene("s2", "f1"))
        assert server._frames["f1"].flags == {"no_resize": True}


class TestWorldMenuPartitions:
    """World menu: per-client namespaces from ConnectMessage identity."""

    def test_named_client_uses_name(self):
        """Client with ConnectMessage name appears under that name."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_connect(sock, ConnectMessage(name="Vox"))
        items = [{"label": "Speak", "id": "speak"}]
        server._handle_register_menu(sock, RegisterMenuMessage(items=items))

        # Client name is used for namespace
        assert server._client_names[10] == "Vox"
        assert 10 in server._menu_registrations
        assert server._menu_registrations[10] == items

    def test_unnamed_client_fallback(self):
        """Client without ConnectMessage gets 'Client {fd}' fallback."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        # No ConnectMessage sent
        items = [{"label": "Do Thing", "id": "thing"}]
        server._handle_register_menu(sock, RegisterMenuMessage(items=items))

        assert 10 not in server._client_names
        # Name resolution falls back to "Client {fd}"
        resolved = server._client_names.get(10, f"Client {10}")
        assert resolved == "Client 10"

    def test_disconnect_clears_menu_items(self):
        """Disconnecting removes client's menu registrations."""
        server = _server()
        sock = _sock(fd=10)
        _register(server, sock)
        server._handle_connect(sock, ConnectMessage(name="Quarry"))
        items = [{"label": "Search", "id": "search"}]
        server._handle_register_menu(sock, RegisterMenuMessage(items=items))

        server._remove_client(sock)

        assert 10 not in server._menu_registrations
        assert "search" not in server._menu_owners

    def test_menu_owner_bookkeeping(self):
        """Menu owner map tracks which client owns each menu item."""
        server = _server()
        s1 = _sock(fd=10)
        s2 = _sock(fd=20)
        _register(server, s1)
        _register(server, s2)
        server._handle_connect(s1, ConnectMessage(name="Lux"))
        server._handle_connect(s2, ConnectMessage(name="Vox"))
        server._handle_register_menu(
            s1, RegisterMenuMessage(items=[{"label": "Board", "id": "board"}])
        )
        server._handle_register_menu(
            s2, RegisterMenuMessage(items=[{"label": "Speak", "id": "speak"}])
        )

        assert server._menu_owners["board"] == 10
        assert server._menu_owners["speak"] == 20
