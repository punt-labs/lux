"""The proxied display routes over the real facade through TestClient.

Each display fact is proxied over luxd's connection, so a StubPort stands in for
the display: it returns one preset reply and the route maps it. The fault codes
prove the shared OpError -> HTTP mapping: a down display is 503, a timed-out
round-trip is 504.
"""

from __future__ import annotations

from punt_lux.operations.display_reply import DisplayFault, DisplayReplied

from ._fakes import StubPort, make_client

_INFO = {
    "backend": "OpenGL3",
    "window_width": 1280,
    "window_height": 800,
    "fps": 60.0,
    "pid": 4242,
    "uptime_seconds": 12.5,
    "protocol_version": "1",
    "element_kinds": 25,
}


def test_get_display_info_returns_the_typed_record() -> None:
    client = make_client(display_port=StubPort(DisplayReplied(_INFO)))
    resp = client.get("/display")
    assert resp.status_code == 200
    assert resp.json()["backend"] == "OpenGL3"
    assert resp.json()["pid"] == 4242


def test_display_unavailable_maps_to_503() -> None:
    client = make_client(
        display_port=StubPort(DisplayFault(code="display_unavailable"))
    )
    assert client.get("/display").status_code == 503


def test_timeout_maps_to_504() -> None:
    client = make_client(display_port=StubPort(DisplayFault(code="timeout")))
    assert client.get("/display").status_code == 504


def test_get_theme() -> None:
    reply = DisplayReplied({"current": "darcula", "available": ["darcula", "cherry"]})
    client = make_client(display_port=StubPort(reply))
    resp = client.get("/display/theme")
    assert resp.status_code == 200
    assert resp.json()["theme"] == "darcula"


def test_set_theme_happy() -> None:
    reply = DisplayReplied({"current": "cherry", "available": ["darcula", "cherry"]})
    client = make_client(display_port=StubPort(reply))
    resp = client.put("/display/theme", json={"theme": "cherry"})
    assert resp.status_code == 200
    assert resp.json()["theme"] == "cherry"


def test_set_theme_rejects_an_unknown_name_with_422() -> None:
    client = make_client(display_port=StubPort(DisplayReplied({})))
    resp = client.put("/display/theme", json={"theme": "not_a_theme"})
    assert resp.status_code == 422


def test_get_window_settings() -> None:
    reply = DisplayReplied(
        {"opacity": 0.9, "font_scale": 1.0, "decorated": True, "fps_idle": 10.0}
    )
    client = make_client(display_port=StubPort(reply))
    resp = client.get("/display/window")
    assert resp.status_code == 200
    assert resp.json()["opacity"] == 0.9


def test_set_window_settings_patch() -> None:
    reply = DisplayReplied(
        {"opacity": 0.5, "font_scale": 1.0, "decorated": True, "fps_idle": 10.0}
    )
    client = make_client(display_port=StubPort(reply))
    resp = client.patch("/display/window", json={"opacity": 0.5})
    assert resp.status_code == 200
    assert resp.json()["opacity"] == 0.5


def test_set_window_settings_rejects_out_of_range_opacity_with_422() -> None:
    # WindowSettingsPatch range-checks opacity at bind time, before any proxy.
    client = make_client(display_port=StubPort(DisplayReplied({})))
    assert client.patch("/display/window", json={"opacity": 5.0}).status_code == 422


def test_set_frame_state() -> None:
    reply = DisplayReplied({"frame_id": "f1", "changed": {"minimized": True}})
    client = make_client(display_port=StubPort(reply))
    resp = client.patch("/display/frames/f1", json={"minimized": True})
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok"}


def test_set_frame_state_rejects_an_unknown_field_with_422() -> None:
    # FrameStatePatch forbids extra fields; a stray key is a bind-time rejection.
    client = make_client(display_port=StubPort(DisplayReplied({})))
    assert client.patch("/display/frames/f1", json={"bogus": True}).status_code == 422


def test_set_frame_state_id_mismatch_is_502() -> None:
    # The display acked a different frame than requested — a backend fault, not a
    # caller error (409) or a down display (503).
    reply = DisplayReplied({"frame_id": "other", "changed": {"minimized": True}})
    client = make_client(display_port=StubPort(reply))
    assert (
        client.patch("/display/frames/f1", json={"minimized": True}).status_code == 502
    )


def test_screenshot() -> None:
    client = make_client(
        display_port=StubPort(DisplayReplied({"path": "/tmp/shot.png"}))
    )
    resp = client.get("/display/screenshot")
    assert resp.status_code == 200
    assert resp.json()["path"] == "/tmp/shot.png"


def test_screenshot_without_a_path_is_502() -> None:
    # The display replied but carried no path — a backend fault (502), the same
    # class as a bad-reply narrowing failure.
    client = make_client(display_port=StubPort(DisplayReplied({})))
    assert client.get("/display/screenshot").status_code == 502


def test_ping() -> None:
    # No timeout given: the wait is the absence contract — None threads through.
    port = StubPort(DisplayReplied({"rtt_seconds": 0.01}))
    resp = make_client(display_port=port).get("/display/ping")
    assert resp.status_code == 200
    assert resp.json()["rtt_seconds"] == 0.01
    assert port.ping_wait is None


def test_ping_forwards_a_bounded_timeout_to_the_port() -> None:
    # A valid timeout binds and reaches the port as the display-leg wait.
    port = StubPort(DisplayReplied({"rtt_seconds": 0.01}))
    resp = make_client(display_port=port).get("/display/ping?timeout=2")
    assert resp.status_code == 200
    assert port.ping_wait == 2.0


def test_ping_rejects_a_timeout_below_the_floor_with_422() -> None:
    # A sub-100ms probe is unmeasurable; the bound rejects it before any proxy.
    resp = make_client().get("/display/ping?timeout=0.05")
    assert resp.status_code == 422


def test_ping_rejects_a_timeout_above_the_cap_with_422() -> None:
    # A 30s+ wait would hang the round-trip; the bound rejects it at bind time.
    resp = make_client().get("/display/ping?timeout=31")
    assert resp.status_code == 422


def test_ping_without_an_rtt_is_502() -> None:
    client = make_client(display_port=StubPort(DisplayReplied({})))
    assert client.get("/display/ping").status_code == 502


def test_list_recent_events() -> None:
    payload = {
        "events": [
            {"element_id": "b1", "action": "click", "timestamp": 1.0},
        ],
        "total_buffered": 1,
    }
    client = make_client(display_port=StubPort(DisplayReplied(payload)))
    resp = client.get("/events?count=10")
    assert resp.status_code == 200
    assert resp.json()["events"][0]["element_id"] == "b1"


def test_list_errors() -> None:
    payload = {
        "errors": [
            {"timestamp": 1.0, "severity": "error", "message": "boom", "context": "q"},
        ],
        "total_buffered": 1,
    }
    client = make_client(display_port=StubPort(DisplayReplied(payload)))
    resp = client.get("/errors")
    assert resp.status_code == 200
    assert resp.json()["errors"][0]["message"] == "boom"


def test_list_recent_events_rejects_a_negative_count_with_422() -> None:
    # A negative count would slice a surprising subset in the dispatcher; the
    # bound rejects it at bind time before any proxy runs (ForbiddenPort default).
    resp = make_client().get("/events?count=-1")
    assert resp.status_code == 422


def test_list_recent_events_rejects_a_count_over_the_cap_with_422() -> None:
    resp = make_client().get("/events?count=201")
    assert resp.status_code == 422


def test_list_errors_rejects_a_negative_count_with_422() -> None:
    resp = make_client().get("/errors?count=-1")
    assert resp.status_code == 422
