"""Unit tests for DisplayServer state machine logic.

These tests exercise protocol handling, event queue management, and update
patching — all pure logic that doesn't touch ImGui or OpenGL.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from punt_lux.display import DisplayServer
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.protocol import (
    ButtonElement,
    CheckboxElement,
    ClearMessage,
    Element,
    MenuMessage,
    PingMessage,
    RegisterMenuMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    SeparatorElement,
    TextElement,
)
from punt_lux.scene import WidgetState

if TYPE_CHECKING:
    import pytest


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
    return SceneMessage(id=scene_id, elements=elements, frame_id=scene_id)


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
    sock.fileno.return_value = 42
    return sock


# -----------------------------------------------------------------------
# P.1: _emit_event stamps scene_id and appends to queue (not recursion)
# -----------------------------------------------------------------------


class TestEmitEvent:
    def test_stamps_scene_id_and_appends(self) -> None:
        """_emit_event must stamp None scene_id and append to _event_queue."""
        server = _make_server()
        server._current_scene_id = "s1"

        event = RemoteEventHandlerInvocation(element_id="b1", action="click", ts=1.0)
        assert event.scene_id is None

        server._emit_event(event)

        assert len(server._event_queue) == 1
        queued = server._event_queue[0]
        assert queued.scene_id == "s1"
        assert queued.element_id == event.element_id
        assert queued.action == event.action

    def test_preserves_existing_scene_id(self) -> None:
        """_emit_event must not overwrite a pre-set scene_id."""
        server = _make_server()
        server._current_scene_id = "s1"

        event = RemoteEventHandlerInvocation(
            element_id="b1", action="click", ts=1.0, scene_id="s2"
        )
        server._emit_event(event)

        assert len(server._event_queue) == 1
        assert server._event_queue[0].scene_id == "s2"

    def test_framed_scene_render_updates_current_scene_id(self) -> None:
        """Button clicks inside framed scenes were being stamped with
        stale or None scene_id because
        ``_render_framed_scene`` updated only the element renderer's view,
        not ``DisplayServer._current_scene_id``.  The stamp source must
        track the scene actually being rendered, regardless of whether it
        lives in a frame or a top-level tab.
        """
        from punt_lux.scene.frame import Frame

        server = _make_server()
        # Empty element list — the scene_id assignment lives at the top of
        # _render_framed_scene, so the render loop never runs.  Keeps the
        # test free of ImGui context requirements.
        scene = SceneMessage(id="framed-1", elements=[], frame_id="framed-1")
        frame = Frame(
            frame_id="f1",
            title="F1",
            owner_fds={42},
            scenes={"framed-1": scene},
            scene_order=["framed-1"],
            active_tab="framed-1",
        )
        server._scene_manager._scene_widget_state["framed-1"] = WidgetState()

        # Pretend an earlier tab render set _current_scene_id to a stale value.
        server._current_scene_id = "stale-tab"
        server._render_framed_scene(frame, "framed-1")
        assert server._current_scene_id == "framed-1"

    def test_display_factory_local_publish_failure_is_loud(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        server = _make_server()
        button = server._luxd_factory.element_from_dict(
            {
                "kind": "button",
                "id": "publish-button",
                "label": "Publish",
                "handlers": [
                    {
                        "event": "click",
                        "factory": "noop",
                        "wrap": [
                            {"decorator": "publish", "topics": ["openTicket"]},
                        ],
                    }
                ],
            }
        )

        with caplog.at_level(logging.ERROR, logger="punt_lux.domain.element_abc"):
            button.fire(
                ButtonClicked(
                    scene_id=SceneId("scene"),
                    element_id=ElementId("publish-button"),
                    owner_id=ClientId("display"),
                )
            )

        assert "without a real PublishSink wired" in caplog.text

    def test_display_factory_checkbox_publish_handler_is_loud_and_updates_state(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        server = _make_server()
        checkbox = server._luxd_factory.element_from_dict(
            {
                "kind": "checkbox",
                "id": "publish-checkbox",
                "label": "Publish",
                "handlers": [
                    {
                        "event": "changed",
                        "factory": "noop",
                        "wrap": [
                            {"decorator": "publish", "topics": ["openTicket"]},
                        ],
                    }
                ],
            }
        )

        assert isinstance(checkbox, CheckboxElement)
        assert checkbox.handler_count(ValueChanged) == 2

        with caplog.at_level(logging.ERROR, logger="punt_lux.domain.element_abc"):
            checkbox.fire(
                ValueChanged(
                    scene_id=SceneId("scene"),
                    element_id=ElementId("publish-checkbox"),
                    owner_id=ClientId("display"),
                    value=True,
                )
            )

        assert checkbox.value is True
        assert "without a real PublishSink wired" in caplog.text


# -----------------------------------------------------------------------
# Fix 1: Scene replacement and clear must drain the event queue
# -----------------------------------------------------------------------


class TestEventQueueOnSceneChange:
    def test_new_scene_preserves_existing_events(self) -> None:
        server = _make_server()
        sock = _mock_sock()

        # Set up a scene via handle_message
        server._handle_message(sock, _make_scene())
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=1.0, value=True
            )
        )
        assert len(server._event_queue) == 1

        # Receive a new scene (different ID) — events from s1 persist
        new_scene = _make_scene(scene_id="s2")
        server._handle_message(sock, new_scene)

        assert len(server._event_queue) == 1
        assert server._scene_manager.resolve_scene("s2") is not None

    def test_same_scene_id_drains_stale_events(self) -> None:
        server = _make_server()
        sock = _mock_sock()

        # First scene has t1, b1, separator, and an extra button b2
        first = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello", style="heading"),
                ButtonElement(id="b1", label="Keep"),
                ButtonElement(id="b2", label="Remove"),
            ]
        )
        server._handle_message(sock, first)
        # Event for b2 (will be removed in replacement)
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b2", action="b2", ts=1.0, value=True
            )
        )
        # Event for b1 (will survive in replacement)
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=1.0, value=True
            )
        )
        assert len(server._event_queue) == 2

        # Replace with scene that keeps t1, b1 but drops b2
        server._handle_message(sock, _make_scene())

        assert len(server._event_queue) == 1
        assert server._event_queue[0].element_id == "b1"

    def test_clear_message_clears_event_queue(self) -> None:
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene())
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=1.0, value=True
            )
        )

        server._handle_message(sock, ClearMessage())

        assert len(server._event_queue) == 0
        assert _scene_count(server) == 0

    def test_ping_does_not_clear_events(self) -> None:
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene())
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="b1", ts=1.0, value=True
            )
        )

        server._handle_message(sock, PingMessage(ts=1.0))

        # Ping should not affect event queue
        assert len(server._event_queue) == 1

    def test_menu_message_stores_agent_menus(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        menus = [{"label": "Tools", "items": [{"label": "Run", "id": "run"}]}]

        server._handle_message(sock, MenuMessage(menus=menus))

        assert server._menu_manager.agent_menus == menus

    def test_menu_message_replaces_previous_menus(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        server._menu_manager.agent_menus = [{"label": "Old", "items": []}]

        new_menus = [{"label": "New", "items": [{"label": "Go", "id": "go"}]}]
        server._handle_message(sock, MenuMessage(menus=new_menus))

        assert server._menu_manager.agent_menus == new_menus


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
        server._socket_server.clients.append(sock)
        from punt_lux.protocol import FrameReader

        server._socket_server._readers[sock.fileno()] = FrameReader()

        # After _remove_client, sock should not be in _clients
        server._socket_server.remove_client(sock)
        assert sock not in server._socket_server.clients
        assert sock.fileno() not in server._socket_server._readers

        # _read_from_client on a removed socket should be a no-op
        # (reader lookup returns None)
        server._socket_server._read_from_client(sock)
        sock.recv.assert_not_called()

    def test_double_remove_is_idempotent(self) -> None:
        """Calling _remove_client twice must not crash."""
        server = _make_server()
        sock = _mock_sock()
        server._socket_server.clients.append(sock)
        from punt_lux.protocol import FrameReader

        server._socket_server._readers[sock.fileno()] = FrameReader()

        server._socket_server.remove_client(sock)
        assert sock not in server._socket_server.clients

        # Second call is a no-op, not a crash
        server._socket_server.remove_client(sock)
        assert sock not in server._socket_server.clients


# -----------------------------------------------------------------------
# Fix 4: Malformed messages disconnect client instead of crashing
# -----------------------------------------------------------------------


class TestMalformedMessageDisconnects:
    def test_invalid_json_disconnects_client(self) -> None:
        """A client sending invalid JSON should be disconnected, not crash."""
        server = _make_server()
        sock = _mock_sock()
        server._socket_server.clients.append(sock)
        from punt_lux.protocol import FrameReader

        reader = FrameReader()
        server._socket_server._readers[sock.fileno()] = reader

        # Feed a frame with invalid JSON (valid length prefix, bad payload)
        import struct

        bad_payload = b"not json"
        frame = struct.pack("!I", len(bad_payload)) + bad_payload
        sock.recv.return_value = frame

        server._socket_server._read_from_client(sock)

        # Client should be disconnected, not crash
        assert sock not in server._socket_server.clients

    def test_unknown_message_type_keeps_client_connected(self) -> None:
        """A client sending an unknown message type should NOT be disconnected.

        Unknown types return UnknownMessage passthrough, which _handle_message
        logs and skips. This enables forward compatibility — old displays
        gracefully ignore new message types from newer clients.
        """
        import json
        import struct

        server = _make_server()
        sock = _mock_sock()
        server._socket_server.clients.append(sock)
        from punt_lux.protocol import FrameReader

        reader = FrameReader()
        server._socket_server._readers[sock.fileno()] = reader

        payload = json.dumps({"type": "bogus"}).encode("utf-8")
        frame = struct.pack("!I", len(payload)) + payload
        sock.recv.return_value = frame

        server._socket_server._read_from_client(sock)

        assert sock in server._socket_server.clients

    def test_known_type_missing_fields_disconnects_client(self) -> None:
        """A known message type missing required fields raises KeyError.

        _read_from_client catches KeyError and disconnects — prevents
        malformed but type-valid messages from crashing the display.
        """
        import json
        import struct

        server = _make_server()
        sock = _mock_sock()
        server._socket_server.clients.append(sock)
        from punt_lux.protocol import FrameReader

        reader = FrameReader()
        server._socket_server._readers[sock.fileno()] = reader

        # "scene" is a known type, but missing required "id" and "elements"
        payload = json.dumps({"type": "scene"}).encode("utf-8")
        frame = struct.pack("!I", len(payload)) + payload
        sock.recv.return_value = frame

        server._socket_server._read_from_client(sock)

        assert sock not in server._socket_server.clients


class TestFlushEvents:
    def test_flush_clears_queue(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        server._socket_server.clients.append(sock)
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="click", ts=1.0)
        )

        server._flush_events()

        assert len(server._event_queue) == 0

    def test_flush_clears_queue_even_without_clients(self) -> None:
        server = _make_server()
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="click", ts=1.0)
        )

        server._flush_events()

        # Events are cleared to prevent stale accumulation
        assert len(server._event_queue) == 0

    def test_flush_noop_when_no_events(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        server._socket_server.clients.append(sock)

        server._flush_events()

        sock.send.assert_not_called()

    def test_flush_routes_menu_event_to_owner(self) -> None:
        """Tools menu events are sent only to the owning client, not broadcast."""
        server = _make_server()
        owner = _mock_sock_fd(10)
        other = _mock_sock_fd(20)
        server._socket_server.clients.extend([owner, other])
        server._socket_server._fd_to_client[10] = owner
        server._socket_server._fd_to_client[20] = other
        server._menu_manager.menu_owners["tool_a"] = 10
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="tool_a",
                action="menu",
                ts=1.0,
                value={"menu": "World", "item": "Tool A"},
            )
        )

        server._flush_events()

        owner.send.assert_called_once()
        other.send.assert_not_called()

    def test_flush_broadcasts_non_menu_event(self) -> None:
        """Events for element IDs not in _menu_owners broadcast to all."""
        server = _make_server()
        sock1 = _mock_sock_fd(10)
        sock2 = _mock_sock_fd(20)
        server._socket_server.clients.extend([sock1, sock2])
        server._socket_server._fd_to_client[10] = sock1
        server._socket_server._fd_to_client[20] = sock2
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="button_x", action="click", ts=1.0)
        )

        server._flush_events()

        sock1.send.assert_called_once()
        sock2.send.assert_called_once()

    def test_flush_broadcasts_non_menu_action_even_if_in_menu_owners(self) -> None:
        """Non-menu actions broadcast even when element_id is in _menu_owners."""
        server = _make_server()
        sock1 = _mock_sock_fd(10)
        sock2 = _mock_sock_fd(20)
        server._socket_server.clients.extend([sock1, sock2])
        server._socket_server._fd_to_client[10] = sock1
        server._socket_server._fd_to_client[20] = sock2
        server._menu_manager.menu_owners["button_x"] = 10
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="button_x", action="click", ts=1.0)
        )

        server._flush_events()

        sock1.send.assert_called_once()
        sock2.send.assert_called_once()

    def test_flush_broadcasts_agent_menu_even_if_id_in_menu_owners(self) -> None:
        """Agent menu clicks broadcast even when ID collides with _menu_owners."""
        server = _make_server()
        sock1 = _mock_sock_fd(10)
        sock2 = _mock_sock_fd(20)
        server._socket_server.clients.extend([sock1, sock2])
        server._socket_server._fd_to_client[10] = sock1
        server._socket_server._fd_to_client[20] = sock2
        server._menu_manager.menu_owners["tool_a"] = 10
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="tool_a",
                action="menu",
                ts=1.0,
                value={"menu": "Custom", "item": "Tool A"},
            )
        )

        server._flush_events()

        sock1.send.assert_called_once()
        sock2.send.assert_called_once()

    def test_flush_routes_menu_drops_if_owner_disconnected(self) -> None:
        """If owner fd is in _menu_owners but not in _fd_to_client, event is dropped."""
        server = _make_server()
        other = _mock_sock_fd(20)
        server._socket_server.clients.append(other)
        server._socket_server._fd_to_client[20] = other
        server._menu_manager.menu_owners["tool_a"] = 10  # fd 10 not in _fd_to_client
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="tool_a",
                action="menu",
                ts=1.0,
                value={"menu": "World", "item": "Tool A"},
            )
        )

        server._flush_events()

        other.send.assert_not_called()
        assert len(server._event_queue) == 0


class TestModalDismissRevertOnUndeliverable:
    """An undeliverable ``modal_closed`` must revert to Hub truth, not diverge.

    A modal dismiss is optimistic: the renderer latches the popup shut and fires
    ``ModalClosed`` toward the Hub. If that interaction never lands, the Hub
    still holds the modal open — so the display latches are cleared to reopen the
    replica, and a non-modal drop leaves latches untouched.
    """

    @staticmethod
    def _latch_modal(
        server: DisplayServer, scene_id: str, element_id: str
    ) -> WidgetState:
        ws = WidgetState()
        server._scene_manager._scene_widget_state[scene_id] = ws
        ws.set(f"{element_id}{WidgetState.OPEN_SUFFIX}", 1)
        ws.set(f"{element_id}{WidgetState.DISMISS_SUFFIX}", 1)
        return ws

    @staticmethod
    def _queue_modal_closed(
        server: DisplayServer, scene_id: str, element_id: str
    ) -> None:
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id=element_id,
                action="changed",
                event_kind="modal_closed",
                scene_id=scene_id,
                ts=1.0,
                value=None,
            )
        )

    def test_no_client_holds_modal_dismiss_within_bound(self) -> None:
        """A dropped connection holds the close for a reconnect, not reverts it."""
        server = _make_server()
        ws = self._latch_modal(server, "s1", "m1")
        self._queue_modal_closed(server, "s1", "m1")

        server._flush_events()  # no client connected; within the buffer bound

        # The modal stays dismissed -- the close is held for a reconnect, not lost.
        assert ws.get(f"m1{WidgetState.OPEN_SUFFIX}") == 1
        assert ws.get(f"m1{WidgetState.DISMISS_SUFFIX}") == 1
        assert not server._pending.is_empty
        assert len(server._event_queue) == 0

    def test_no_client_reverts_modal_dismiss_past_bound(self) -> None:
        """A close still undelivered past the buffer bound reverts to Hub truth."""
        from punt_lux.display.pending_interactions import PendingInteractions

        server = _make_server()
        server._pending = PendingInteractions(
            max_age=-1.0
        )  # any held event is past bound
        ws = self._latch_modal(server, "s1", "m1")
        self._queue_modal_closed(server, "s1", "m1")

        server._flush_events()  # no client; the close ages out immediately

        assert ws.get(f"m1{WidgetState.OPEN_SUFFIX}") is None
        assert ws.get(f"m1{WidgetState.DISMISS_SUFFIX}") is None
        assert server._pending.is_empty
        assert len(server._event_queue) == 0

    def test_reconnect_delivers_held_modal_dismiss(self) -> None:
        """A held close delivers on reconnect and the dismiss latch holds."""
        server = _make_server()
        self._latch_modal(server, "s1", "m1")
        self._queue_modal_closed(server, "s1", "m1")
        server._flush_events()  # no client: the close is held

        sock = _mock_sock_fd(10)
        server._socket_server.clients.append(sock)
        server._socket_server._fd_to_client[10] = sock
        server._flush_events()  # client back: the held close is delivered

        sock.send.assert_called_once()
        assert server._pending.is_empty

    def test_send_failure_reverts_modal_dismiss_and_removes_client(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        sock.send.side_effect = OSError("boom")
        server._socket_server.clients.append(sock)
        from punt_lux.protocol import FrameReader

        server._socket_server._readers[sock.fileno()] = FrameReader()
        ws = self._latch_modal(server, "s1", "m1")
        self._queue_modal_closed(server, "s1", "m1")

        server._flush_events()

        assert ws.get(f"m1{WidgetState.DISMISS_SUFFIX}") is None
        assert sock not in server._socket_server.clients

    def test_delivered_modal_dismiss_is_not_reverted(self) -> None:
        server = _make_server()
        sock = _mock_sock_fd(10)
        server._socket_server.clients.append(sock)
        server._socket_server._fd_to_client[10] = sock
        ws = self._latch_modal(server, "s1", "m1")
        self._queue_modal_closed(server, "s1", "m1")

        server._flush_events()

        sock.send.assert_called_once()
        # Delivered: the Hub will re-push the removal, so the latch must hold.
        assert ws.get(f"m1{WidgetState.DISMISS_SUFFIX}") == 1

    def test_non_modal_undelivered_event_leaves_latches_untouched(self) -> None:
        server = _make_server()
        ws = self._latch_modal(server, "s1", "m1")
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="b1", action="click", scene_id="s1", ts=1.0
            )
        )

        server._flush_events()  # no client connected

        assert ws.get(f"m1{WidgetState.DISMISS_SUFFIX}") == 1


# -----------------------------------------------------------------------
# Multi-scene (persistent dismissable tabs)
# -----------------------------------------------------------------------


def _scene_count(server: DisplayServer) -> int:
    """Total scenes the display holds, across every frame."""
    return server._scene_manager.scene_count


class TestMultiScene:
    def test_second_scene_creates_a_second_frame(self) -> None:
        """Two scenes with different ids self-frame into two separate frames."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        server._handle_message(sock, _make_scene(scene_id="s2"))

        assert server._scene_manager.resolve_scene("s1") is not None
        assert server._scene_manager.resolve_scene("s2") is not None
        assert set(server._scene_manager.frames) == {"s1", "s2"}

    def test_same_scene_id_replaces_content(self) -> None:
        """Re-sending the same scene_id replaces content in its frame."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[TextElement(id="t1", content="Old")],
            ),
        )
        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[TextElement(id="t1", content="New")],
            ),
        )

        assert _scene_count(server) == 1
        scene = server._scene_manager.resolve_scene("s1")
        assert scene is not None
        elem = scene.elements[0]
        assert isinstance(elem, TextElement)
        assert elem.content == "New"

    def test_resend_replaces_domain_display_state(self) -> None:
        """Re-send of basics-only scene must replace, not duplicate, domain state.

        Bug-A regression guard: ``Display.apply`` returns ``DuplicateIdError``
        on a colliding AddElement.  Before the fix, the second SceneMessage
        AddElement'd every element again and the errors were swallowed —
        the domain snapshot froze on the first scene while SceneManager
        kept updating.  After the fix, the domain Display reflects the
        SECOND scene's content.
        """
        from punt_lux.domain.ids import ElementId, SceneId

        server = _make_server()
        sock = _mock_sock()

        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[TextElement(id="t1", content="first")],
            ),
        )
        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[TextElement(id="t1", content="second")],
            ),
        )

        snap = server._domain_display.snapshot(SceneId("s1"))
        stored = snap.element(ElementId("t1"))
        assert isinstance(stored, TextElement)
        assert stored.content == "second"

    def test_clear_removes_all_scenes(self) -> None:
        """ClearMessage removes all scenes and resets tab state."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        server._handle_message(sock, _make_scene(scene_id="s2"))
        server._handle_message(sock, ClearMessage())

        assert _scene_count(server) == 0
        assert len(server._scene_manager.frames) == 0
        assert len(server._scene_manager._scene_widget_state) == 0

    def test_widget_state_isolated_per_scene(self) -> None:
        """Each scene gets its own WidgetState instance."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        server._handle_message(sock, _make_scene(scene_id="s2"))

        ws1 = server._scene_manager._scene_widget_state["s1"]
        ws2 = server._scene_manager._scene_widget_state["s2"]

        ws1.set("slider1", 42)
        assert ws2.get("slider1") is None

    def test_empty_push_removes_a_scene_and_its_frame(self) -> None:
        """An empty push removes the scene from its frame and closes the frame."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        server._handle_message(sock, _make_scene(scene_id="s2"))

        server._handle_message(sock, _make_scene(scene_id="s1", elements=[]))

        assert server._scene_manager.resolve_scene("s1") is None
        assert "s1" not in server._scene_manager.frames
        assert "s1" not in server._scene_manager._scene_widget_state
        assert server._scene_manager.resolve_scene("s2") is not None

    def test_each_scene_is_its_frames_active_tab(self) -> None:
        """A self-framed scene is the active tab of the frame it creates."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        assert server._scene_manager.frames["s1"].active_tab == "s1"

        server._handle_message(sock, _make_scene(scene_id="s2"))
        assert server._scene_manager.frames["s2"].active_tab == "s2"

    def test_dismiss_drains_events_for_dismissed_scene(self) -> None:
        """Dismissing a scene removes its unique events from the queue."""
        server = _make_server()
        sock = _mock_sock()

        # s1 has unique elements not shared with s2
        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[
                    ButtonElement(id="s1_btn", label="S1"),
                    TextElement(id="s1_txt", content="S1"),
                ],
            ),
        )
        server._handle_message(
            sock,
            _make_scene(
                scene_id="s2",
                elements=[ButtonElement(id="s2_btn", label="S2")],
            ),
        )

        # Queue events for s1's elements
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="s1_btn", action="s1_btn", ts=1.0, value=True
            )
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="s1_txt", action="s1_txt", ts=1.0, value=True
            )
        )
        assert len(server._event_queue) == 2

        # Dismiss s1 — its events should be drained
        _sm = server._scene_manager
        _sm.dismiss_framed_scene(_sm.frames["s1"], "s1")

        assert len(server._event_queue) == 0

    def test_dismiss_preserves_events_from_other_scenes(self) -> None:
        """Dismissing one scene does not drain events from other scenes."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[ButtonElement(id="btn_s1", label="S1")],
            ),
        )
        server._handle_message(
            sock,
            _make_scene(
                scene_id="s2",
                elements=[ButtonElement(id="btn_s2", label="S2")],
            ),
        )

        # Events from both scenes
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="btn_s1", action="btn_s1", ts=1.0, value=True
            )
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="btn_s2", action="btn_s2", ts=1.0, value=True
            )
        )

        # Dismiss s1 — only s1's events drained
        _sm = server._scene_manager
        _sm.dismiss_framed_scene(_sm.frames["s1"], "s1")

        assert len(server._event_queue) == 1
        assert server._event_queue[0].element_id == "btn_s2"

    def test_dismiss_preserves_events_for_shared_element_ids(self) -> None:
        """Dismissing a scene with shared IDs keeps events alive for survivors."""
        server = _make_server()
        sock = _mock_sock()

        # Both scenes share element ID "shared_btn"
        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[
                    ButtonElement(id="shared_btn", label="S1"),
                    ButtonElement(id="s1_only", label="S1 Only"),
                ],
            ),
        )
        server._handle_message(
            sock,
            _make_scene(
                scene_id="s2",
                elements=[ButtonElement(id="shared_btn", label="S2")],
            ),
        )

        # Events for shared and unique IDs
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="shared_btn", action="click", ts=1.0, value=True
            )
        )
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="s1_only", action="click", ts=1.0, value=True
            )
        )

        # Dismiss s1 — shared_btn survives in s2, s1_only does not
        _sm = server._scene_manager
        _sm.dismiss_framed_scene(_sm.frames["s1"], "s1")

        assert len(server._event_queue) == 1
        assert server._event_queue[0].element_id == "shared_btn"


# -----------------------------------------------------------------------
# RegisterMenuMessage: additive menu registration per client
# -----------------------------------------------------------------------


def _mock_sock_fd(fd: int) -> MagicMock:
    """Create a mock socket with a specific fileno()."""
    sock = MagicMock()
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
    sock.fileno.return_value = fd
    return sock


class TestRegisterMenu:
    def test_register_stores_items(self) -> None:
        """RegisterMenuMessage stores items in _menu_registrations and _menu_owners."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        items = [
            {"label": "Run", "id": "run"},
            {"label": "Test", "id": "test"},
        ]

        server._handle_message(sock, RegisterMenuMessage(items=items))

        assert server._menu_manager.menu_registrations[10] == items
        assert server._menu_manager.menu_owners["run"] == 10
        assert server._menu_manager.menu_owners["test"] == 10

    def test_disconnect_cleans_up(self) -> None:
        """Disconnecting a client removes its menu registrations and ownership."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        server._socket_server.clients.append(sock)
        from punt_lux.protocol import FrameReader

        server._socket_server._readers[10] = FrameReader()
        server._socket_server._fd_to_client[10] = sock

        items = [{"label": "Run", "id": "run"}]
        server._handle_message(sock, RegisterMenuMessage(items=items))

        assert 10 in server._menu_manager.menu_registrations
        assert "run" in server._menu_manager.menu_owners

        server._socket_server.remove_client(sock)

        assert 10 not in server._menu_manager.menu_registrations
        assert "run" not in server._menu_manager.menu_owners

    def test_re_register_replaces_old_items(self) -> None:
        """Same client re-registering replaces old items."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        old_items = [{"label": "Old", "id": "old_item"}]
        new_items = [{"label": "New", "id": "new_item"}]

        server._handle_message(sock, RegisterMenuMessage(items=old_items))
        assert server._menu_manager.menu_owners.get("old_item") == 10

        server._handle_message(sock, RegisterMenuMessage(items=new_items))
        assert server._menu_manager.menu_registrations[10] == new_items
        assert "old_item" not in server._menu_manager.menu_owners
        assert server._menu_manager.menu_owners["new_item"] == 10

    def test_id_uniqueness_rejects_second_client(self) -> None:
        """Two different clients registering the same item ID: second is rejected."""
        server = _make_server()
        sock_a = _mock_sock_fd(10)
        sock_b = _mock_sock_fd(20)

        items_a = [{"label": "Run", "id": "run"}]
        items_b = [{"label": "Also Run", "id": "run"}]

        server._handle_message(sock_a, RegisterMenuMessage(items=items_a))
        server._handle_message(sock_b, RegisterMenuMessage(items=items_b))

        # Client A's registration stands
        assert server._menu_manager.menu_registrations[10] == items_a
        assert server._menu_manager.menu_owners["run"] == 10
        # Client B's registration was rejected
        assert 20 not in server._menu_manager.menu_registrations

    def test_clear_does_not_clear_menu_registrations(self) -> None:
        """ClearMessage clears scenes but not menu registrations."""
        server = _make_server()
        sock = _mock_sock_fd(10)

        items = [{"label": "Run", "id": "run"}]
        server._handle_message(sock, RegisterMenuMessage(items=items))
        server._handle_message(sock, ClearMessage())

        assert server._menu_manager.menu_registrations[10] == items
        assert server._menu_manager.menu_owners["run"] == 10

    def test_non_dict_items_filtered(self) -> None:
        """Non-dict entries in items list are silently filtered."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        items: list[Any] = [
            {"label": "Good", "id": "good"},
            "not a dict",
            42,
            {"label": "Also Good", "id": "also_good"},
        ]
        server._handle_message(sock, RegisterMenuMessage(items=items))
        assert len(server._menu_manager.menu_registrations[10]) == 2
        assert server._menu_manager.menu_owners["good"] == 10
        assert server._menu_manager.menu_owners["also_good"] == 10

    def test_non_string_id_filtered(self) -> None:
        """Items with non-string IDs are silently filtered."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        items: list[dict[str, Any]] = [
            {"label": "Good", "id": "good"},
            {"label": "Bad ID", "id": 123},
            {"label": "List ID", "id": ["a"]},
        ]
        server._handle_message(sock, RegisterMenuMessage(items=items))
        assert len(server._menu_manager.menu_registrations[10]) == 1
        assert server._menu_manager.menu_owners["good"] == 10

    def test_duplicate_ids_within_registration_deduped(self) -> None:
        """Duplicate IDs within a single registration keep first."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        items = [
            {"label": "First", "id": "dup"},
            {"label": "Second", "id": "dup"},
        ]
        server._handle_message(sock, RegisterMenuMessage(items=items))
        assert len(server._menu_manager.menu_registrations[10]) == 1
        assert server._menu_manager.menu_registrations[10][0]["label"] == "First"

    def test_empty_items_clears_registration(self) -> None:
        """Registering empty items removes client from _menu_registrations."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        items = [{"label": "Run", "id": "run"}]
        server._handle_message(sock, RegisterMenuMessage(items=items))
        assert 10 in server._menu_manager.menu_registrations

        server._handle_message(sock, RegisterMenuMessage(items=[]))
        assert 10 not in server._menu_manager.menu_registrations
        assert "run" not in server._menu_manager.menu_owners
