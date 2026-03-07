"""Unit tests for DisplayServer state machine logic.

These tests exercise protocol handling, event queue management, and update
patching — all pure logic that doesn't touch ImGui or OpenGL.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.display import DisplayServer
from punt_lux.protocol import (
    ButtonElement,
    ClearMessage,
    Element,
    InteractionMessage,
    Patch,
    PingMessage,
    SceneMessage,
    SeparatorElement,
    TextElement,
    UpdateMessage,
)


def _make_server() -> DisplayServer:
    """Create a DisplayServer without starting the socket or ImGui."""
    return DisplayServer("/tmp/test-lux-unit.sock")


def _make_scene(
    scene_id: str = "s1",
    elements: list[Element] | None = None,
) -> SceneMessage:
    if elements is None:
        elements = [
            TextElement(id="t1", content="Hello", style="heading"),
            ButtonElement(id="b1", label="Click"),
            SeparatorElement(),
        ]
    return SceneMessage(id=scene_id, elements=elements)


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.sendall = MagicMock()
    sock.fileno.return_value = 42
    return sock


# -----------------------------------------------------------------------
# Fix 1: Scene replacement and clear must drain the event queue
# -----------------------------------------------------------------------


class TestEventQueueClearedOnSceneReplace:
    def test_new_scene_clears_stale_events(self) -> None:
        server = _make_server()
        sock = _mock_sock()

        # Set up a scene and queue an event
        server._current_scene = _make_scene()
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )
        assert len(server._event_queue) == 1

        # Receive a new scene
        new_scene = _make_scene(scene_id="s2")
        server._handle_message(sock, new_scene)

        # Event queue must be empty — old events are stale
        assert len(server._event_queue) == 0
        assert server._current_scene is not None
        assert server._current_scene.id == "s2"

    def test_clear_message_clears_event_queue(self) -> None:
        server = _make_server()
        sock = _mock_sock()

        server._current_scene = _make_scene()
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )

        server._handle_message(sock, ClearMessage())

        assert len(server._event_queue) == 0
        assert server._current_scene is None

    def test_ping_does_not_clear_events(self) -> None:
        server = _make_server()
        sock = _mock_sock()

        server._current_scene = _make_scene()
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )

        server._handle_message(sock, PingMessage(ts=1.0))

        # Ping should not affect event queue
        assert len(server._event_queue) == 1


# -----------------------------------------------------------------------
# Fix 2: _poll_clients skips sockets removed during error handling
# -----------------------------------------------------------------------


class TestPollClientsSkipsRemoved:
    def test_errored_socket_not_read(self) -> None:
        """A socket in both errored and readable sets should only be removed,
        not read from after removal."""
        server = _make_server()
        sock = _mock_sock()

        # Manually register the client
        server._clients.append(sock)
        from punt_lux.protocol import FrameReader

        server._readers[sock.fileno()] = FrameReader()

        # After _remove_client, sock should not be in _clients
        server._remove_client(sock)
        assert sock not in server._clients
        assert sock.fileno() not in server._readers

        # _read_from_client on a removed socket should be a no-op
        # (reader lookup returns None)
        server._read_from_client(sock)
        sock.recv.assert_not_called()


# -----------------------------------------------------------------------
# Fix 3: _apply_update must not mutate id or kind
# -----------------------------------------------------------------------


class TestApplyUpdateProtectsIdentity:
    def test_patch_cannot_change_element_id(self) -> None:
        server = _make_server()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello"),
                TextElement(id="t2", content="World"),
            ]
        )
        server._current_scene = scene

        # Try to change t1's id to t2 (would break unique-ID invariant)
        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"id": "t2"})],
        )
        server._apply_update(msg)

        # ID must not have changed
        ids = [e.id for e in server._current_scene.elements]
        assert ids == ["t1", "t2"]

    def test_patch_cannot_change_element_kind(self) -> None:
        server = _make_server()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello"),
            ]
        )
        server._current_scene = scene

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"kind": "button"})],
        )
        server._apply_update(msg)

        assert server._current_scene.elements[0].kind == "text"

    def test_patch_can_change_content(self) -> None:
        server = _make_server()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello"),
            ]
        )
        server._current_scene = scene

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"content": "Updated"})],
        )
        server._apply_update(msg)

        elem = server._current_scene.elements[0]
        assert isinstance(elem, TextElement)
        assert elem.content == "Updated"

    def test_patch_remove_element(self) -> None:
        server = _make_server()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello"),
                TextElement(id="t2", content="World"),
            ]
        )
        server._current_scene = scene

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", remove=True)],
        )
        server._apply_update(msg)

        assert len(server._current_scene.elements) == 1
        assert server._current_scene.elements[0].id == "t2"

    def test_update_wrong_scene_id_is_noop(self) -> None:
        server = _make_server()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello"),
            ]
        )
        server._current_scene = scene

        msg = UpdateMessage(
            scene_id="wrong-id",
            patches=[Patch(id="t1", set={"content": "Changed"})],
        )
        server._apply_update(msg)

        elem = server._current_scene.elements[0]
        assert isinstance(elem, TextElement)
        assert elem.content == "Hello"


# -----------------------------------------------------------------------
# Flush events: broadcast and clear
# -----------------------------------------------------------------------


# -----------------------------------------------------------------------
# Fix 4: Malformed messages disconnect client instead of crashing
# -----------------------------------------------------------------------


class TestMalformedMessageDisconnects:
    def test_invalid_json_disconnects_client(self) -> None:
        """A client sending invalid JSON should be disconnected, not crash."""
        server = _make_server()
        sock = _mock_sock()
        server._clients.append(sock)
        from punt_lux.protocol import FrameReader

        reader = FrameReader()
        server._readers[sock.fileno()] = reader

        # Feed a frame with invalid JSON (valid length prefix, bad payload)
        import struct

        bad_payload = b"not json"
        frame = struct.pack("!I", len(bad_payload)) + bad_payload
        sock.recv.return_value = frame

        server._read_from_client(sock)

        # Client should be disconnected, not crash
        assert sock not in server._clients

    def test_unknown_message_type_disconnects_client(self) -> None:
        """A client sending an unknown message type should be disconnected."""
        import json
        import struct

        server = _make_server()
        sock = _mock_sock()
        server._clients.append(sock)
        from punt_lux.protocol import FrameReader

        reader = FrameReader()
        server._readers[sock.fileno()] = reader

        payload = json.dumps({"type": "bogus"}).encode("utf-8")
        frame = struct.pack("!I", len(payload)) + payload
        sock.recv.return_value = frame

        server._read_from_client(sock)

        assert sock not in server._clients


class TestFlushEvents:
    def test_flush_clears_queue(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        server._clients.append(sock)
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="click", ts=1.0)
        )

        server._flush_events()

        assert len(server._event_queue) == 0

    def test_flush_clears_queue_even_without_clients(self) -> None:
        server = _make_server()
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="click", ts=1.0)
        )

        server._flush_events()

        # Events are cleared to prevent stale accumulation
        assert len(server._event_queue) == 0

    def test_flush_noop_when_no_events(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        server._clients.append(sock)

        server._flush_events()

        sock.sendall.assert_not_called()
