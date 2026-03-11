"""Unit tests for DisplayServer state machine logic.

These tests exercise protocol handling, event queue management, and update
patching — all pure logic that doesn't touch ImGui or OpenGL.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.display import DisplayServer, WidgetState, _parse_color
from punt_lux.protocol import (
    ButtonElement,
    ClearMessage,
    Element,
    InteractionMessage,
    MenuMessage,
    Patch,
    PingMessage,
    RegisterMenuMessage,
    SceneMessage,
    SeparatorElement,
    TextElement,
    UpdateMessage,
    WindowElement,
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


def _inject_scene(server: DisplayServer, scene: SceneMessage) -> None:
    """Directly inject a scene into multi-scene state (bypasses message handling)."""
    server._scenes[scene.id] = scene
    if scene.id not in server._scene_order:
        server._scene_order.append(scene.id)
    server._scene_widget_state[scene.id] = WidgetState()
    server._scene_render_fn_state[scene.id] = {}
    server._active_tab = scene.id


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
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )
        assert len(server._event_queue) == 1

        # Receive a new scene (different ID) — events from s1 persist
        new_scene = _make_scene(scene_id="s2")
        server._handle_message(sock, new_scene)

        assert len(server._event_queue) == 1
        assert "s2" in server._scenes

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
            InteractionMessage(element_id="b2", action="b2", ts=1.0, value=True)
        )
        # Event for b1 (will survive in replacement)
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
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
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )

        server._handle_message(sock, ClearMessage())

        assert len(server._event_queue) == 0
        assert len(server._scenes) == 0

    def test_ping_does_not_clear_events(self) -> None:
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene())
        server._event_queue.append(
            InteractionMessage(element_id="b1", action="b1", ts=1.0, value=True)
        )

        server._handle_message(sock, PingMessage(ts=1.0))

        # Ping should not affect event queue
        assert len(server._event_queue) == 1

    def test_menu_message_stores_agent_menus(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        menus = [{"label": "Tools", "items": [{"label": "Run", "id": "run"}]}]

        server._handle_message(sock, MenuMessage(menus=menus))

        assert server._agent_menus == menus

    def test_menu_message_replaces_previous_menus(self) -> None:
        server = _make_server()
        sock = _mock_sock()
        server._agent_menus = [{"label": "Old", "items": []}]

        new_menus = [{"label": "New", "items": [{"label": "Go", "id": "go"}]}]
        server._handle_message(sock, MenuMessage(menus=new_menus))

        assert server._agent_menus == new_menus


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

    def test_double_remove_is_idempotent(self) -> None:
        """Calling _remove_client twice must not crash."""
        server = _make_server()
        sock = _mock_sock()
        server._clients.append(sock)
        from punt_lux.protocol import FrameReader

        server._readers[sock.fileno()] = FrameReader()

        server._remove_client(sock)
        assert sock not in server._clients

        # Second call is a no-op, not a crash
        server._remove_client(sock)
        assert sock not in server._clients


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
        _inject_scene(server, scene)

        # Try to change t1's id to t2 (would break unique-ID invariant)
        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"id": "t2"})],
        )
        server._apply_update(msg)

        # ID must not have changed
        ids = [e.id for e in server._scenes["s1"].elements]
        assert ids == ["t1", "t2"]

    def test_patch_cannot_change_element_kind(self) -> None:
        server = _make_server()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello"),
            ]
        )
        _inject_scene(server, scene)

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"kind": "button"})],
        )
        server._apply_update(msg)

        assert server._scenes["s1"].elements[0].kind == "text"

    def test_patch_can_change_content(self) -> None:
        server = _make_server()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello"),
            ]
        )
        _inject_scene(server, scene)

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"content": "Updated"})],
        )
        server._apply_update(msg)

        elem = server._scenes["s1"].elements[0]
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
        _inject_scene(server, scene)

        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", remove=True)],
        )
        server._apply_update(msg)

        assert len(server._scenes["s1"].elements) == 1
        assert server._scenes["s1"].elements[0].id == "t2"

    def test_update_wrong_scene_id_is_noop(self) -> None:
        server = _make_server()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Hello"),
            ]
        )
        _inject_scene(server, scene)

        msg = UpdateMessage(
            scene_id="wrong-id",
            patches=[Patch(id="t1", set={"content": "Changed"})],
        )
        server._apply_update(msg)

        elem = server._scenes["s1"].elements[0]
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
        server._clients.append(sock)
        from punt_lux.protocol import FrameReader

        reader = FrameReader()
        server._readers[sock.fileno()] = reader

        payload = json.dumps({"type": "bogus"}).encode("utf-8")
        frame = struct.pack("!I", len(payload)) + payload
        sock.recv.return_value = frame

        server._read_from_client(sock)

        assert sock in server._clients

    def test_known_type_missing_fields_disconnects_client(self) -> None:
        """A known message type missing required fields raises KeyError.

        _read_from_client catches KeyError and disconnects — prevents
        malformed but type-valid messages from crashing the display.
        """
        import json
        import struct

        server = _make_server()
        sock = _mock_sock()
        server._clients.append(sock)
        from punt_lux.protocol import FrameReader

        reader = FrameReader()
        server._readers[sock.fileno()] = reader

        # "scene" is a known type, but missing required "id" and "elements"
        payload = json.dumps({"type": "scene"}).encode("utf-8")
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


# -----------------------------------------------------------------------
# Multi-scene (persistent dismissable tabs)
# -----------------------------------------------------------------------


class TestMultiScene:
    def test_second_scene_creates_tab(self) -> None:
        """Sending two scenes with different IDs keeps both in _scenes."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        server._handle_message(sock, _make_scene(scene_id="s2"))

        assert "s1" in server._scenes
        assert "s2" in server._scenes
        assert server._scene_order == ["s1", "s2"]

    def test_same_scene_id_replaces_content(self) -> None:
        """Re-sending the same scene_id replaces content, no new tab."""
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

        assert len(server._scenes) == 1
        assert server._scene_order == ["s1"]
        elem = server._scenes["s1"].elements[0]
        assert isinstance(elem, TextElement)
        assert elem.content == "New"

    def test_update_routes_to_correct_scene(self) -> None:
        """Update targets a specific scene by scene_id."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[TextElement(id="t1", content="S1")],
            ),
        )
        server._handle_message(
            sock,
            _make_scene(
                scene_id="s2",
                elements=[TextElement(id="t2", content="S2")],
            ),
        )

        # Update s2 only
        server._apply_update(
            UpdateMessage(
                scene_id="s2",
                patches=[Patch(id="t2", set={"content": "Updated"})],
            )
        )

        # s1 untouched
        s1_elem = server._scenes["s1"].elements[0]
        assert isinstance(s1_elem, TextElement)
        assert s1_elem.content == "S1"
        # s2 updated
        s2_elem = server._scenes["s2"].elements[0]
        assert isinstance(s2_elem, TextElement)
        assert s2_elem.content == "Updated"

    def test_update_to_unknown_scene_is_dropped(self) -> None:
        """Update for a dismissed/unknown scene_id is silently dropped."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(
            sock,
            _make_scene(
                scene_id="s1",
                elements=[TextElement(id="t1", content="Hello")],
            ),
        )

        # Update for non-existent scene — no error
        server._apply_update(
            UpdateMessage(
                scene_id="gone",
                patches=[Patch(id="t1", set={"content": "Nope"})],
            )
        )

        elem = server._scenes["s1"].elements[0]
        assert isinstance(elem, TextElement)
        assert elem.content == "Hello"

    def test_clear_removes_all_scenes(self) -> None:
        """ClearMessage removes all scenes and resets tab state."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        server._handle_message(sock, _make_scene(scene_id="s2"))
        server._handle_message(sock, ClearMessage())

        assert len(server._scenes) == 0
        assert server._scene_order == []
        assert server._active_tab is None
        assert len(server._scene_widget_state) == 0
        assert len(server._scene_render_fn_state) == 0

    def test_scene_order_preserved(self) -> None:
        """Scenes appear in insertion order."""
        server = _make_server()
        sock = _mock_sock()

        for sid in ["s1", "s2", "s3"]:
            server._handle_message(sock, _make_scene(scene_id=sid))

        assert server._scene_order == ["s1", "s2", "s3"]

    def test_widget_state_isolated_per_scene(self) -> None:
        """Each scene gets its own WidgetState instance."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        server._handle_message(sock, _make_scene(scene_id="s2"))

        ws1 = server._scene_widget_state["s1"]
        ws2 = server._scene_widget_state["s2"]

        ws1.set("slider1", 42)
        assert ws2.get("slider1") is None

    def test_dismiss_scene_removes_state(self) -> None:
        """Dismissing a scene cleans up all associated state."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        server._handle_message(sock, _make_scene(scene_id="s2"))

        server._dismiss_scene("s1")

        assert "s1" not in server._scenes
        assert server._scene_order == ["s2"]
        assert "s1" not in server._scene_widget_state
        assert "s1" not in server._scene_render_fn_state
        assert server._active_tab == "s2"

    def test_dismiss_middle_tab_selects_next_neighbor(self) -> None:
        """Dismissing the middle tab selects the next tab (browser behavior)."""
        server = _make_server()
        sock = _mock_sock()

        for sid in ["s1", "s2", "s3"]:
            server._handle_message(sock, _make_scene(scene_id=sid))

        # Active is s3 (latest). Switch to s2 to test middle dismiss.
        server._active_tab = "s2"
        server._dismiss_scene("s2")

        assert server._scene_order == ["s1", "s3"]
        assert server._active_tab == "s3"  # next neighbor, not first

    def test_dismiss_last_tab_selects_previous(self) -> None:
        """Dismissing the rightmost tab selects the one before it."""
        server = _make_server()
        sock = _mock_sock()

        for sid in ["s1", "s2", "s3"]:
            server._handle_message(sock, _make_scene(scene_id=sid))

        server._active_tab = "s3"
        server._dismiss_scene("s3")

        assert server._scene_order == ["s1", "s2"]
        assert server._active_tab == "s2"  # previous, not first

    def test_dismiss_first_tab_selects_next(self) -> None:
        """Dismissing the first tab selects the second tab."""
        server = _make_server()
        sock = _mock_sock()

        for sid in ["s1", "s2", "s3"]:
            server._handle_message(sock, _make_scene(scene_id=sid))

        server._active_tab = "s1"
        server._dismiss_scene("s1")

        assert server._scene_order == ["s2", "s3"]
        assert server._active_tab == "s2"

    def test_active_tab_set_to_newest_scene(self) -> None:
        """Each new scene becomes the active tab."""
        server = _make_server()
        sock = _mock_sock()

        server._handle_message(sock, _make_scene(scene_id="s1"))
        assert server._active_tab == "s1"

        server._handle_message(sock, _make_scene(scene_id="s2"))
        assert server._active_tab == "s2"

    def test_same_scene_id_does_not_dirty_windows(self) -> None:
        """Re-sending a scene with the same ID should not force window positions."""
        server = _make_server()
        sock = _mock_sock()
        win = WindowElement(id="w1", title="Panel", x=10, y=10)
        scene = SceneMessage(id="s1", elements=[win])

        server._handle_message(sock, scene)
        assert "w1" in server._dirty_windows

        # Consume the dirty flag (simulates first render)
        server._dirty_windows.clear()

        # Same scene ID again — windows should NOT be re-dirtied
        server._handle_message(sock, scene)
        assert "w1" not in server._dirty_windows

    def test_new_scene_id_dirties_windows(self) -> None:
        """A new scene ID should mark windows dirty for initial positioning."""
        server = _make_server()
        sock = _mock_sock()
        win = WindowElement(id="w1", title="Panel", x=10, y=10)

        server._handle_message(sock, SceneMessage(id="s1", elements=[win]))
        server._dirty_windows.clear()

        server._handle_message(sock, SceneMessage(id="s2", elements=[win]))
        assert "w1" in server._dirty_windows

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
            InteractionMessage(element_id="s1_btn", action="s1_btn", ts=1.0, value=True)
        )
        server._event_queue.append(
            InteractionMessage(element_id="s1_txt", action="s1_txt", ts=1.0, value=True)
        )
        assert len(server._event_queue) == 2

        # Dismiss s1 — its events should be drained
        server._dismiss_scene("s1")

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
            InteractionMessage(element_id="btn_s1", action="btn_s1", ts=1.0, value=True)
        )
        server._event_queue.append(
            InteractionMessage(element_id="btn_s2", action="btn_s2", ts=1.0, value=True)
        )

        # Dismiss s1 — only s1's events drained
        server._dismiss_scene("s1")

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
            InteractionMessage(
                element_id="shared_btn", action="click", ts=1.0, value=True
            )
        )
        server._event_queue.append(
            InteractionMessage(element_id="s1_only", action="click", ts=1.0, value=True)
        )

        # Dismiss s1 — shared_btn survives in s2, s1_only does not
        server._dismiss_scene("s1")

        assert len(server._event_queue) == 1
        assert server._event_queue[0].element_id == "shared_btn"


# -----------------------------------------------------------------------
# Color parsing: hex strings and RGBA lists/tuples
# -----------------------------------------------------------------------


class TestParseColor:
    def test_hex_rgb(self) -> None:
        assert _parse_color("#FF8000") == (255, 128, 0, 255)

    def test_hex_rgba(self) -> None:
        assert _parse_color("#FF800080") == (255, 128, 0, 128)

    def test_hex_no_hash(self) -> None:
        assert _parse_color("FF8000") == (255, 128, 0, 255)

    def test_list_rgb(self) -> None:
        assert _parse_color([70, 130, 230]) == (70, 130, 230, 255)

    def test_list_rgba(self) -> None:
        assert _parse_color([70, 130, 230, 128]) == (70, 130, 230, 128)

    def test_tuple_rgba(self) -> None:
        assert _parse_color((200, 80, 60, 255)) == (200, 80, 60, 255)

    def test_list_extra_components_ignored(self) -> None:
        assert _parse_color([10, 20, 30, 40, 50, 60]) == (10, 20, 30, 40)

    def test_list_too_short_fallback(self) -> None:
        assert _parse_color([10, 20]) == (255, 255, 255, 255)

    def test_empty_list_fallback(self) -> None:
        assert _parse_color([]) == (255, 255, 255, 255)

    def test_list_non_numeric_fallback(self) -> None:
        assert _parse_color(["x", "y", "z"]) == (255, 255, 255, 255)

    def test_list_none_elements_fallback(self) -> None:
        assert _parse_color([None, None, None]) == (255, 255, 255, 255)

    def test_invalid_hex_fallback(self) -> None:
        assert _parse_color("#ZZZZZZ") == (255, 255, 255, 255)

    def test_float_list_truncated_to_int(self) -> None:
        assert _parse_color([70.9, 130.1, 230.5]) == (70, 130, 230, 255)

    def test_none_fallback(self) -> None:
        assert _parse_color(None) == (255, 255, 255, 255)

    def test_int_fallback(self) -> None:
        assert _parse_color(42) == (255, 255, 255, 255)


# -----------------------------------------------------------------------
# RegisterMenuMessage: additive menu registration per client
# -----------------------------------------------------------------------


def _mock_sock_fd(fd: int) -> MagicMock:
    """Create a mock socket with a specific fileno()."""
    sock = MagicMock()
    sock.sendall = MagicMock()
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

        assert server._menu_registrations[10] == items
        assert server._menu_owners["run"] == 10
        assert server._menu_owners["test"] == 10

    def test_disconnect_cleans_up(self) -> None:
        """Disconnecting a client removes its menu registrations and ownership."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        server._clients.append(sock)
        from punt_lux.protocol import FrameReader

        server._readers[10] = FrameReader()
        server._fd_to_client[10] = sock

        items = [{"label": "Run", "id": "run"}]
        server._handle_message(sock, RegisterMenuMessage(items=items))

        assert 10 in server._menu_registrations
        assert "run" in server._menu_owners

        server._remove_client(sock)

        assert 10 not in server._menu_registrations
        assert "run" not in server._menu_owners

    def test_re_register_replaces_old_items(self) -> None:
        """Same client re-registering replaces old items."""
        server = _make_server()
        sock = _mock_sock_fd(10)
        old_items = [{"label": "Old", "id": "old_item"}]
        new_items = [{"label": "New", "id": "new_item"}]

        server._handle_message(sock, RegisterMenuMessage(items=old_items))
        assert server._menu_owners.get("old_item") == 10

        server._handle_message(sock, RegisterMenuMessage(items=new_items))
        assert server._menu_registrations[10] == new_items
        assert "old_item" not in server._menu_owners
        assert server._menu_owners["new_item"] == 10

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
        assert server._menu_registrations[10] == items_a
        assert server._menu_owners["run"] == 10
        # Client B's registration was rejected
        assert 20 not in server._menu_registrations

    def test_clear_does_not_clear_menu_registrations(self) -> None:
        """ClearMessage clears scenes but not menu registrations."""
        server = _make_server()
        sock = _mock_sock_fd(10)

        items = [{"label": "Run", "id": "run"}]
        server._handle_message(sock, RegisterMenuMessage(items=items))
        server._handle_message(sock, ClearMessage())

        assert server._menu_registrations[10] == items
        assert server._menu_owners["run"] == 10
