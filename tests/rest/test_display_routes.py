"""The proxied display routes over the real facade through TestClient.

Each display fact is proxied over luxd's connection, so a StubPort stands in for
the display: it returns one preset reply and the route maps it. The fault codes
prove the shared OpError -> HTTP mapping: a down display is 503, a timed-out
round-trip is 504.
"""

from __future__ import annotations

import os
import socket

from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
)
from punt_lux.wire.operations.hub_connection import HubConnection

from ._fakes import StubPort, make_client

_INFO = {
    "backend": "OpenGL3",
    "window_width": 1280,
    "window_height": 800,
    "fps": 60.0,
    "pid": 4242,
    "hub_connection_id": "spoofed",
    "uptime_seconds": 12.5,
    "protocol_version": "1",
    "element_kinds": 25,
}


def test_get_display_info_returns_the_typed_record() -> None:
    client = make_client(
        display_port=StubPort(
            DisplayReplied(
                _INFO, connection=HubConnection.model_validate("hub-start:1")
            )
        )
    )
    resp = client.get("/display")
    assert resp.status_code == 200
    assert resp.json()["backend"] == "OpenGL3"
    assert resp.json()["pid"] == 4242
    assert resp.json()["hub_connection_id"] == "hub-start:1"


def test_display_unavailable_maps_to_503() -> None:
    client = make_client(display_port=StubPort(DisplayFault.UNAVAILABLE))
    assert client.get("/display").status_code == 503


def test_timeout_maps_to_504() -> None:
    client = make_client(display_port=StubPort(DisplayFault.TIMEOUT))
    assert client.get("/display").status_code == 504


def test_get_theme() -> None:
    reply = DisplayReplied({"current": "darcula", "available": ["darcula", "cherry"]})
    client = make_client(display_port=StubPort(reply))
    resp = client.get("/display/theme")
    assert resp.status_code == 200
    assert resp.json()["theme"] == "darcula"


def test_get_window_settings() -> None:
    reply = DisplayReplied(
        {"opacity": 0.9, "font_scale": 1.0, "decorated": True, "fps_idle": 10.0}
    )
    client = make_client(display_port=StubPort(reply))
    resp = client.get("/display/window")
    assert resp.status_code == 200
    assert resp.json()["opacity"] == 0.9


def test_list_frames_reports_a_docked_frame_over_http() -> None:
    # The whole point of the route: a frame the user docked is still listed, with
    # its visibility, so it is verifiable from outside the display process.
    reply = DisplayReplied(
        {
            "scenes": [],
            "frames": [
                {
                    "frame_id": "f1",
                    "title": "Music",
                    "scene_count": 1,
                    "scene_ids": ["s1"],
                    "layout": "tab",
                    "visibility": "docked",
                }
            ],
        }
    )
    client = make_client(display_port=StubPort(reply))

    resp = client.get("/display/frames")

    assert resp.status_code == 200
    assert resp.json() == {
        "kind": "ok",
        "frames": [
            {
                "frame_id": "f1",
                "title": "Music",
                "visibility": "docked",
                "scene_ids": ["s1"],
            }
        ],
    }


def test_screenshot_returns_the_path_the_display_painted() -> None:
    port = StubPort(DisplayReplied({"path": "/tmp/lux-screenshots/a.png"}))
    resp = make_client(display_port=port).get("/display/screenshot")
    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok", "path": "/tmp/lux-screenshots/a.png"}


def test_anonymous_screenshot_is_rejected_with_the_challenge() -> None:
    # A screenshot writes a file on the display host, so like every other write
    # it needs a named caller: an identity-less request is challenged and the
    # display is never asked.
    # No display port: the default ForbiddenPort fails the test if it is reached.
    resp = make_client(identity={}).get("/display/screenshot")
    assert resp.status_code == 401
    assert "X-Lux-Identification-Required" in resp.headers


def test_a_named_screenshot_registers_no_session() -> None:
    # The capture needs a named caller but owns no UI, so it must not record a
    # Hub session: a capture-only app with the never-expiring app lease would
    # otherwise stay in the session list after it exits.
    port = StubPort(DisplayReplied({"path": "/tmp/lux-screenshots/a.png"}))
    client = make_client(display_port=port)
    assert client.get("/display/screenshot").status_code == 200
    assert client.get("/clients").json()["clients"] == []


def test_a_malformed_identity_on_screenshot_is_422_not_anonymous() -> None:
    # A writer must declare a valid identity: a garbled lease is a named
    # rejection, not a fall-through to the anonymous reader.
    headers = {"X-Lux-Client-Name": "demo", "X-Lux-Client-Lease-Ttl": "soon"}
    resp = make_client(identity=headers).get("/display/screenshot")
    assert resp.status_code == 422


def test_screenshot_refused_by_the_display_is_409() -> None:
    port = StubPort(DisplayErrored("a screenshot is already waiting"))
    resp = make_client(display_port=port).get("/display/screenshot")
    assert resp.status_code == 409
    assert "already waiting" in resp.json()["detail"]


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


def test_get_link_reports_disconnected_with_no_display() -> None:
    # ForbiddenPort (the default) is not connected and asserts nothing else is
    # touched -- get_link never round-trips, so a disconnected display is fine.
    resp = make_client().get("/display/link")
    assert resp.status_code == 200
    assert resp.json() == {
        "kind": "disconnected",
        "linkage": "disconnected",
        "live_scene_count": 0,
        "retry_delay_seconds": 0.0,
        "hub_host": socket.gethostname(),
        "hub_pid": os.getpid(),
    }


def test_get_link_reports_connected_idle() -> None:
    client = make_client(display_port=StubPort(DisplayReplied({})))
    resp = client.get("/display/link")
    assert resp.status_code == 200
    assert resp.json() == {
        "kind": "connected",
        "linkage": "connected_idle",
        "live_scene_count": 0,
        "hub_host": socket.gethostname(),
        "hub_pid": os.getpid(),
    }
