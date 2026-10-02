"""Characterization tests for QueryRouter extraction from RenderLoop."""

from __future__ import annotations

from typing import Any

import pytest

from punt_lux.display.query_dispatcher import DisplayQueryHandlers, QueryRouter
from punt_lux.display.replica import SceneReplica
from punt_lux.protocol import QueryResponse, SceneMessage, TextElement


def _make_dispatcher(scenes: SceneReplica | None = None) -> QueryRouter:
    """Build a QueryRouter with stub callables for testing."""
    sm = (
        scenes
        if scenes is not None
        else SceneReplica(on_scene_replaced=lambda _i: None)
    )
    return QueryRouter(
        scenes=sm,
        get_client_names=dict,
        get_client_connect_times=dict,
        get_agent_menus=list,
        get_callback_menus=list,
    )


def _scene(scene_id: str, frame_id: str) -> SceneMessage:
    """A non-empty framed push — an empty one is a removal, not a scene."""
    return SceneMessage(
        id=scene_id,
        elements=[TextElement(id=f"{scene_id}-t", content="x")],
        frame_id=frame_id,
    )


class TestDispatchKnownMethod:
    def test_registered_handler_returns_result(self) -> None:
        """Register a handler, send a query, verify response carries the result."""
        qd = _make_dispatcher()

        def echo_handler(**kwargs: Any) -> dict[str, Any]:
            return {"echo": kwargs}

        qd.register_handler("echo", echo_handler)
        resp = qd.handle_query("echo", {"key": "value"})

        assert isinstance(resp, QueryResponse)
        assert resp.method == "echo"
        assert resp.result == {"echo": {"key": "value"}}
        assert resp.error is None


class TestDispatchUnknownMethod:
    def test_unregistered_method_returns_error(self) -> None:
        """Query for an unregistered method returns an error response."""
        qd = _make_dispatcher()
        resp = qd.handle_query("nonexistent", None)

        assert isinstance(resp, QueryResponse)
        assert resp.method == "nonexistent"
        assert resp.error == "Unknown method: nonexistent"


class TestRecordEventRingBuffer:
    def test_ring_buffer_caps_at_200(self) -> None:
        """Record 250 events, verify only the last 200 are retained."""
        qd = _make_dispatcher()
        for i in range(250):
            qd.record_event({"index": i})

        result = qd.handle_query("list_recent_events", {"count": 200})
        events = result.result["events"]
        assert len(events) == 200
        assert result.result["total_buffered"] == 200
        # First retained event should be index 50 (250 - 200)
        assert events[0]["index"] == 50
        assert events[-1]["index"] == 249


class TestRecordErrorRingBuffer:
    def test_ring_buffer_caps_at_100(self) -> None:
        """Record 150 errors, verify only the last 100 are retained."""
        qd = _make_dispatcher()
        for i in range(150):
            qd.record_error("error", f"msg-{i}", f"ctx-{i}")

        result = qd.handle_query("list_errors", {"count": 100})
        errors = result.result["errors"]
        assert len(errors) == 100
        assert result.result["total_buffered"] == 100
        # First retained error should be msg-50 (150 - 100)
        assert errors[0]["message"] == "msg-50"
        assert errors[-1]["message"] == "msg-149"


class TestListRecentEventsWithCount:
    def test_count_limits_returned_events(self) -> None:
        """Record events, query with count, verify limiting works."""
        qd = _make_dispatcher()
        for i in range(20):
            qd.record_event({"index": i})

        result = qd.handle_query("list_recent_events", {"count": 5})
        events = result.result["events"]
        assert len(events) == 5
        assert result.result["total_buffered"] == 20
        # Should return the last 5 events
        assert events[0]["index"] == 15
        assert events[-1]["index"] == 19


class TestListScenesReportsVisibility:
    """V7 — the payload says where each frame is, so the fix is observable.

    Closing a frame stopped removing it, which means an observer outside the
    Display can no longer tell "the user shut it" from "it is up" by the frame's
    presence alone. The visibility is the distinction, so it rides the payload.
    """

    @staticmethod
    def _frames(qd: QueryRouter) -> dict[str, str]:
        """Return frame id → the visibility the payload reports for it."""
        result = qd.handle_query("list_scenes", None).result
        return {f["frame_id"]: f["visibility"] for f in result["frames"]}

    def test_each_visibility_is_reported_by_name(self) -> None:
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        qd = _make_dispatcher(scenes)
        for fid, sid in (("f1", "s1"), ("f2", "s2"), ("f3", "s3")):
            scenes.handle_framed_scene(_scene(sid, fid), owner_fd=10)
        scenes.minimize("f2")
        scenes.close("f3")

        assert self._frames(qd) == {
            "f1": "on_screen",
            "f2": "docked",
            "f3": "closed",
        }

    def test_a_closed_frame_still_reports_the_scenes_it_holds(self) -> None:
        """Closed is not gone: the content behind the shut window is still listed."""
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        qd = _make_dispatcher(scenes)
        scenes.handle_framed_scene(_scene("s1", "f1"), owner_fd=10)

        scenes.close("f1")

        frames = qd.handle_query("list_scenes", None).result["frames"]
        assert frames == [
            {
                "frame_id": "f1",
                "title": "f1",
                "scene_count": 1,
                "scene_ids": ["s1"],
                "layout": "tab",
                "visibility": "closed",
            }
        ]


class TestDisplayStateQuery:
    def test_reports_curated_scene_widget_state_and_frame_presentations(self) -> None:
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        qd = _make_dispatcher(scenes)
        scenes.handle_framed_scene(_scene("s1", "f1"), owner_fd=10)
        state = scenes.widget_state_for("s1")
        assert state is not None
        state.set("checkbox1", value=True)

        result = qd.handle_query("display_state", {}).result

        assert result["scenes"] == {"s1": {"checkbox1": True}}
        assert result["frames"] == [
            {
                "frame_id": "f1",
                "visibility": "on_screen",
                "active_tab": "s1",
                "cascade_index": 0,
            }
        ]

    def test_an_empty_replica_reports_no_scenes_or_frames(self) -> None:
        qd = _make_dispatcher()
        result = qd.handle_query("display_state", {}).result
        assert result == {"scenes": {}, "frames": []}


def _handlers(**overrides: Any) -> DisplayQueryHandlers:
    """Build a DisplayQueryHandlers with stub getters, any overridden."""
    defaults: dict[str, Any] = {
        "get_start_time": lambda: 0.0,
        "get_opacity": lambda: 1.0,
        "get_font_scale": lambda: 1.1,
        "get_decorated": lambda: True,
        "get_current_theme": lambda: "imgui_colors_dark",
        "get_themes": list,
    }
    defaults.update(overrides)
    return DisplayQueryHandlers(**defaults)


class TestScreenshotHandler:
    def test_refuses_the_generic_query_path(self) -> None:
        """Screenshots need GL context; the dedicated request message is required."""
        with pytest.raises(RuntimeError, match="screenshot_request"):
            _handlers().screenshot()


class TestGetThemeHandler:
    def test_reports_the_current_theme_and_available_names(self) -> None:
        theme = type("Theme", (), {"name": "imgui_colors_light"})()
        count = type("Theme", (), {"name": "count"})()  # the sentinel, excluded

        result = _handlers(
            get_current_theme=lambda: "imgui_colors_light",
            get_themes=lambda: [theme, count],
        ).get_theme()

        assert result == {
            "current": "imgui_colors_light",
            "available": ["imgui_colors_light"],
        }


# get_window_settings and get_display_info both read the live ImGui runner
# via hello_imgui, which requires a real GL context (HelloImGui::Run()) --
# the same reason the original _query_get_display_info was never unit
# tested headless. Their pure inputs (opacity/font_scale/decorated/theme
# getters) are exercised through the other handlers above.
