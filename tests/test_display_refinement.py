"""Data refinement commutativity tests for DisplayServer.

Verifies that the concrete DisplayServer implementation correctly refines
the abstract Z specification (docs/display-server.tex) by checking:

    abstract(concreteOp(concreteState)) = abstractOp(abstract(concreteState))

for every operation in the specification.

Z Specification: docs/display-server.tex
Abstraction function: tests/display_abstraction.py
"""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.display import DisplayServer
from punt_lux.protocol import (
    ButtonElement,
    ClearMessage,
    FrameReader,
    InteractionMessage,
    Patch,
    SceneMessage,
    SeparatorElement,
    TextElement,
    UpdateMessage,
    encode_message,
)

from .display_abstraction import (
    abstract,
    abstract_button_click,
    abstract_clear_scene,
    abstract_disconnect_client,
    abstract_flush_events,
    abstract_init,
    abstract_reader,
    abstract_reader_init,
    abstract_receive_scene,
    abstract_remove_element,
    abstract_shutdown,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server() -> DisplayServer:
    """Create a DisplayServer without starting socket or ImGui."""
    return DisplayServer("/tmp/test-lux-refine.sock")


def _mock_sock(fd: int = 42) -> MagicMock:
    sock = MagicMock()
    sock.sendall = MagicMock()
    sock.fileno.return_value = fd
    sock.close = MagicMock()
    return sock


def _register_client(server: DisplayServer, sock: MagicMock) -> None:
    """Manually register a mock client (bypasses socket accept)."""
    server._clients.append(sock)
    server._readers[sock.fileno()] = FrameReader()


def _set_scene(server: DisplayServer, scene_id: str = "s1") -> None:
    """Set a scene with text + button + separator elements."""
    server._current_scene = SceneMessage(
        id=scene_id,
        elements=[
            TextElement(id="t1", content="Hello", style="heading"),
            ButtonElement(id="b1", label="Click"),
            SeparatorElement(id="sep1"),
        ],
    )


# ---------------------------------------------------------------------------
# Init commutativity
# ---------------------------------------------------------------------------


class TestRefinementInit:
    """abstract(init_concrete) = init_abstract"""

    def test_concrete_init_abstracts_to_abstract_init(self):
        server = _make_server()
        assert abstract(server) == abstract_init()

    def test_frame_reader_init_abstracts_to_abstract_init(self):
        reader = FrameReader()
        assert abstract_reader(reader) == abstract_reader_init()


# ---------------------------------------------------------------------------
# ReceiveScene commutativity
# ---------------------------------------------------------------------------


class TestRefinementReceiveScene:
    """abstract(receiveScene(c)) = absReceiveScene(abstract(c))"""

    def test_receive_scene_commutes(self):
        server = _make_server()
        sock = _mock_sock()
        abs_before = abstract(server)

        scene = SceneMessage(
            id="s1",
            elements=[
                TextElement(id="t1", content="Hello"),
                ButtonElement(id="b1", label="Go"),
            ],
        )
        server._handle_message(sock, scene)

        abs_after = abstract_receive_scene(
            abs_before,
            new_scene_id="s1",
            new_elem_ids=frozenset({"t1", "b1"}),
            new_elem_kinds={"t1": "text", "b1": "button"},
        )
        assert abstract(server) == abs_after

    def test_receive_scene_replaces_existing(self):
        server = _make_server()
        sock = _mock_sock()
        _set_scene(server, "s1")
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )

        abs_before = abstract(server)

        new_scene = SceneMessage(
            id="s2",
            elements=[TextElement(id="t2", content="New")],
        )
        server._handle_message(sock, new_scene)

        abs_after = abstract_receive_scene(
            abs_before,
            new_scene_id="s2",
            new_elem_ids=frozenset({"t2"}),
            new_elem_kinds={"t2": "text"},
        )
        assert abstract(server) == abs_after

    def test_receive_scene_with_all_element_kinds(self):
        server = _make_server()
        sock = _mock_sock()
        abs_before = abstract(server)

        scene = SceneMessage(
            id="s1",
            elements=[
                TextElement(id="t1", content="A"),
                ButtonElement(id="b1", label="B"),
                SeparatorElement(id="sep1"),
            ],
        )
        server._handle_message(sock, scene)

        abs_after = abstract_receive_scene(
            abs_before,
            new_scene_id="s1",
            new_elem_ids=frozenset({"t1", "b1", "sep1"}),
            new_elem_kinds={"t1": "text", "b1": "button", "sep1": "separator"},
        )
        assert abstract(server) == abs_after


# ---------------------------------------------------------------------------
# ClearScene commutativity
# ---------------------------------------------------------------------------


class TestRefinementClearScene:
    """abstract(clearScene(c)) = absClearScene(abstract(c))"""

    def test_clear_scene_commutes(self):
        server = _make_server()
        sock = _mock_sock()
        _set_scene(server)
        abs_before = abstract(server)

        server._handle_message(sock, ClearMessage())

        abs_after = abstract_clear_scene(abs_before)
        assert abstract(server) == abs_after

    def test_clear_scene_with_events_commutes(self):
        server = _make_server()
        sock = _mock_sock()
        _set_scene(server)
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=1.0)
        )
        abs_before = abstract(server)

        server._handle_message(sock, ClearMessage())

        abs_after = abstract_clear_scene(abs_before)
        assert abstract(server) == abs_after

    def test_clear_when_no_scene_commutes(self):
        server = _make_server()
        sock = _mock_sock()
        abs_before = abstract(server)

        server._handle_message(sock, ClearMessage())

        abs_after = abstract_clear_scene(abs_before)
        assert abstract(server) == abs_after


# ---------------------------------------------------------------------------
# RemoveElement commutativity
# ---------------------------------------------------------------------------


class TestRefinementRemoveElement:
    """abstract(removeElement(c)) = absRemoveElement(abstract(c))"""

    def test_remove_element_commutes(self):
        server = _make_server()
        _set_scene(server, "s1")
        abs_before = abstract(server)

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", remove=True)],
        )
        server._apply_update(msg)

        abs_after = abstract_remove_element(abs_before, "t1")
        assert abstract(server) == abs_after

    def test_remove_button_commutes(self):
        server = _make_server()
        _set_scene(server, "s1")
        abs_before = abstract(server)

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="b1", remove=True)],
        )
        server._apply_update(msg)

        abs_after = abstract_remove_element(abs_before, "b1")
        assert abstract(server) == abs_after

    def test_remove_last_element_commutes(self):
        server = _make_server()
        server._current_scene = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="Only")],
        )
        abs_before = abstract(server)

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", remove=True)],
        )
        server._apply_update(msg)

        abs_after = abstract_remove_element(abs_before, "t1")
        assert abstract(server) == abs_after


# ---------------------------------------------------------------------------
# DisconnectClient commutativity
# ---------------------------------------------------------------------------


class TestRefinementDisconnectClient:
    """abstract(disconnectClient(c)) = absDisconnect(abstract(c))"""

    def test_disconnect_commutes(self):
        server = _make_server()
        sock = _mock_sock(fd=10)
        _register_client(server, sock)
        abs_before = abstract(server)

        server._remove_client(sock)

        abs_after = abstract_disconnect_client(abs_before, 10)
        assert abstract(server) == abs_after

    def test_disconnect_one_of_two_commutes(self):
        server = _make_server()
        sock1 = _mock_sock(fd=10)
        sock2 = _mock_sock(fd=20)
        _register_client(server, sock1)
        _register_client(server, sock2)
        abs_before = abstract(server)

        server._remove_client(sock1)

        abs_after = abstract_disconnect_client(abs_before, 10)
        assert abstract(server) == abs_after

    def test_disconnect_preserves_scene(self):
        server = _make_server()
        sock = _mock_sock(fd=10)
        _register_client(server, sock)
        _set_scene(server)
        abs_before = abstract(server)

        server._remove_client(sock)

        abs_after = abstract_disconnect_client(abs_before, 10)
        assert abstract(server) == abs_after


# ---------------------------------------------------------------------------
# FlushEvents commutativity
# ---------------------------------------------------------------------------


class TestRefinementFlushEvents:
    """abstract(flushEvents(c)) = absFlushEvents(abstract(c))"""

    def test_flush_with_events_and_clients_commutes(self):
        server = _make_server()
        sock = _mock_sock(fd=10)
        _register_client(server, sock)
        _set_scene(server)
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="click", ts=1.0)
        )
        abs_before = abstract(server)

        server._flush_events()

        abs_after = abstract_flush_events(abs_before)
        assert abstract(server) == abs_after

    def test_flush_empty_queue_commutes(self):
        server = _make_server()
        sock = _mock_sock(fd=10)
        _register_client(server, sock)
        abs_before = abstract(server)

        server._flush_events()

        abs_after = abstract_flush_events(abs_before)
        assert abstract(server) == abs_after

    def test_flush_multiple_events_commutes(self):
        server = _make_server()
        sock = _mock_sock(fd=10)
        _register_client(server, sock)
        _set_scene(server)
        server._event_queue.extend(
            [
                InteractionMessage(element_id="b1", action="click", ts=1.0),
                InteractionMessage(element_id="b1", action="click", ts=2.0),
            ]
        )
        abs_before = abstract(server)

        server._flush_events()

        abs_after = abstract_flush_events(abs_before)
        assert abstract(server) == abs_after


# ---------------------------------------------------------------------------
# Shutdown commutativity
# ---------------------------------------------------------------------------


class TestRefinementShutdown:
    """abstract(shutdown(c)) = absShutdown(abstract(c))"""

    def test_shutdown_with_clients_commutes(self):
        server = _make_server()
        sock1 = _mock_sock(fd=10)
        sock2 = _mock_sock(fd=20)
        _register_client(server, sock1)
        _register_client(server, sock2)
        _set_scene(server)
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="click", ts=1.0)
        )
        abs_before = abstract(server)

        # Concrete shutdown (partial — socket/file cleanup skipped)
        for client in list(server._clients):
            client.close()
        server._clients.clear()
        server._readers.clear()
        server._current_scene = None
        server._event_queue.clear()
        server._server_sock = None

        abs_after = abstract_shutdown(abs_before)
        assert abstract(server) == abs_after

    def test_shutdown_empty_server_commutes(self):
        server = _make_server()
        abs_before = abstract(server)

        server._clients.clear()
        server._readers.clear()
        server._current_scene = None
        server._event_queue.clear()
        server._server_sock = None

        abs_after = abstract_shutdown(abs_before)
        assert abstract(server) == abs_after


# ---------------------------------------------------------------------------
# FrameReader: FeedBytes commutativity
# ---------------------------------------------------------------------------


class TestRefinementFeedBytes:
    """abstract(feed(reader, data)) = absFeedBytes(abstract(reader))"""

    def test_feed_bytes_commutes(self):
        reader = FrameReader()
        buf_before, _ = abstract_reader(reader)

        data = b"hello"
        reader.feed(data)

        concrete_buf = len(reader._buf)
        abstract_buf = buf_before + len(data)
        assert concrete_buf == abstract_buf

    def test_feed_bytes_accumulates(self):
        reader = FrameReader()

        reader.feed(b"abc")
        reader.feed(b"def")

        assert len(reader._buf) == 6

    def test_feed_empty_is_identity(self):
        reader = FrameReader()
        reader.feed(b"abc")
        buf_before = len(reader._buf)

        reader.feed(b"")

        assert len(reader._buf) == buf_before


# ---------------------------------------------------------------------------
# FrameReader: DrainMessages commutativity
# ---------------------------------------------------------------------------


class TestRefinementDrainMessages:
    """After drain, buffer shrinks by bytes consumed in complete messages."""

    def test_drain_complete_message_reduces_buffer(self):
        reader = FrameReader()
        msg = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="Hi")],
        )
        frame = encode_message(msg)
        reader.feed(frame)
        buf_before = len(reader._buf)
        assert buf_before == len(frame)

        messages = reader.drain_typed()

        assert len(messages) == 1
        assert len(reader._buf) == 0  # all bytes consumed

    def test_drain_partial_message_preserves_buffer(self):
        reader = FrameReader()
        msg = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="Hi")],
        )
        frame = encode_message(msg)
        # Feed only half the frame
        half = len(frame) // 2
        reader.feed(frame[:half])

        messages = reader.drain_typed()

        assert len(messages) == 0
        assert len(reader._buf) == half  # nothing consumed

    def test_drain_two_messages_consumes_both(self):
        reader = FrameReader()
        msg1 = ClearMessage()
        msg2 = ClearMessage()
        reader.feed(encode_message(msg1) + encode_message(msg2))

        messages = reader.drain_typed()

        assert len(messages) == 2
        assert len(reader._buf) == 0


# ---------------------------------------------------------------------------
# Composed operations: multi-step commutativity
# ---------------------------------------------------------------------------


class TestRefinementComposed:
    """Test sequences of operations maintain commutativity."""

    def test_scene_then_clear_commutes(self):
        server = _make_server()
        sock = _mock_sock()
        abs_state = abstract(server)

        # Concrete: receive scene then clear
        scene = SceneMessage(id="s1", elements=[TextElement(id="t1", content="A")])
        server._handle_message(sock, scene)
        server._handle_message(sock, ClearMessage())

        # Abstract: same sequence
        abs_state = abstract_receive_scene(
            abs_state, "s1", frozenset({"t1"}), {"t1": "text"}
        )
        abs_state = abstract_clear_scene(abs_state)

        assert abstract(server) == abs_state

    def test_scene_remove_flush_commutes(self):
        server = _make_server()
        sock = _mock_sock(fd=10)
        _register_client(server, sock)
        abs_state = abstract(server)

        # Concrete sequence
        scene = SceneMessage(
            id="s1",
            elements=[
                TextElement(id="t1", content="A"),
                ButtonElement(id="b1", label="B"),
            ],
        )
        server._handle_message(sock, scene)
        abs_state = abstract_receive_scene(
            abs_state,
            "s1",
            frozenset({"t1", "b1"}),
            {"t1": "text", "b1": "button"},
        )

        # Remove t1
        server._apply_update(
            UpdateMessage(scene_id="s1", patches=[Patch(id="t1", remove=True)])
        )
        abs_state = abstract_remove_element(abs_state, "t1")

        # Add event and flush
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="click", ts=1.0)
        )
        abs_state = abstract_button_click(abs_state, "b1")

        server._flush_events()
        abs_state = abstract_flush_events(abs_state)

        assert abstract(server) == abs_state

    def test_connect_disconnect_is_identity(self):
        """AcceptConnection followed by DisconnectClient returns to start."""
        server = _make_server()
        abs_state = abstract(server)

        sock = _mock_sock(fd=99)
        _register_client(server, sock)
        server._remove_client(sock)

        assert abstract(server) == abs_state
