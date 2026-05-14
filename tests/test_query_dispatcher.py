"""Characterization tests for QueryDispatcher extraction from DisplayServer."""

from __future__ import annotations

from typing import Any

from punt_lux.protocol import QueryResponse
from punt_lux.query_dispatcher import QueryDispatcher
from punt_lux.scene_manager import SceneManager


def _make_dispatcher() -> QueryDispatcher:
    """Build a QueryDispatcher with stub callables for testing."""
    sm = SceneManager(on_scene_replaced=lambda _ids: None)
    return QueryDispatcher(
        scene_manager=sm,
        get_client_names=dict,
        get_client_connect_times=dict,
        get_menu_registrations=dict,
        get_agent_menus=list,
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
