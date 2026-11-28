"""DisplayControlOperations — the proxied display-fact reads and writes.

Every operation reaches the display through the injected ``DisplayPort``; these
tests drive a fake port so the mapping from a bounded reply to a typed result or
an ``OpError`` is verified without a socket. The regression the suite guards is
the ``get_display_info`` schema drift: the display's real payload must validate
against the model the output schema is derived from.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from punt_lux.operations.display_control import DisplayControlOperations
from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
    DisplayReply,
)
from punt_lux.wire.operations.common import OpError
from punt_lux.wire.operations.display_frames import FrameStates
from punt_lux.wire.operations.display_info import DisplayInfo
from punt_lux.wire.operations.display_probe import Pong, Screenshot
from punt_lux.wire.operations.display_write import FrameStatePatch
from punt_lux.wire.operations.menu_results import Ok
from punt_lux.wire.operations.theme import ThemeState
from punt_lux.wire.operations.window import WindowSettings

# The exact payload the display's ``_query_get_display_info`` returns today.
_LIVE_DISPLAY_INFO: dict[str, object] = {
    "backend": "OpenGL3",
    "window_width": 1200,
    "window_height": 800,
    "fps": 60.0,
    "pid": 4321,
    "uptime_seconds": 12.5,
    "protocol_version": "1.0",
    "element_kinds": 25,
}


class _FakePort:
    """A DisplayPort that returns a preset reply and records the last call."""

    _query_reply: DisplayReply
    _ping_reply: DisplayReply
    _last_method: str
    _last_params: Mapping[str, object]
    _last_wait: float | None

    def __new__(
        cls, *, query: DisplayReply | None = None, ping: DisplayReply | None = None
    ) -> Self:
        self = super().__new__(cls)
        self._query_reply = query if query is not None else DisplayReplied(payload={})
        self._ping_reply = ping if ping is not None else DisplayReplied(payload={})
        self._last_method = ""
        self._last_params = {}
        self._last_wait = None
        return self

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        self._last_method = method
        self._last_params = params
        return self._query_reply

    def ping(self, wait: float | None) -> DisplayReply:
        self._last_wait = wait
        return self._ping_reply

    @property
    def last_method(self) -> str:
        return self._last_method

    @property
    def last_params(self) -> Mapping[str, object]:
        return self._last_params

    @property
    def last_wait(self) -> float | None:
        return self._last_wait

    @property
    def is_connected(self) -> bool:
        return True


def _ops(port: _FakePort) -> DisplayControlOperations:
    """Build a ``DisplayControlOperations`` over a fake port."""
    return DisplayControlOperations(port)


def test_get_display_info_accepts_the_live_display_payload() -> None:
    # The drift defect: the display's real 8-field payload must validate against
    # the model the MCP output schema is derived from.
    ops = _ops(_FakePort(query=DisplayReplied(_LIVE_DISPLAY_INFO)))
    result = ops.get_display_info()
    assert isinstance(result, DisplayInfo)
    assert result.backend == "OpenGL3"
    assert result.element_kinds == 25


def test_get_display_info_maps_unavailable_to_op_error() -> None:
    ops = _ops(_FakePort(query=DisplayFault.UNAVAILABLE))
    result = ops.get_display_info()
    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"


def test_get_display_info_maps_timeout_to_op_error() -> None:
    ops = _ops(_FakePort(query=DisplayFault.TIMEOUT))
    result = ops.get_display_info()
    assert isinstance(result, OpError)
    assert result.code == "timeout"


def test_get_theme_passes_the_bare_theme_names_through() -> None:
    # The display answers with bare theme names (its own enum names); the
    # operation validates them against the ThemeName set as-is.
    payload = {
        "current": "darcula",
        "available": ["imgui_colors_light", "darcula", "gray_variations"],
    }
    ops = _ops(_FakePort(query=DisplayReplied(payload)))
    result = ops.get_theme()
    assert isinstance(result, ThemeState)
    assert result.theme == "darcula"
    assert result.available == ["imgui_colors_light", "darcula", "gray_variations"]


def test_get_theme_faults_on_an_unknown_theme_name() -> None:
    # A reply the model cannot narrow is a malformed display reply — an
    # engine-side fault, not a caller error — and fails loudly, not silently.
    payload = {"current": "not_a_theme", "available": []}
    ops = _ops(_FakePort(query=DisplayReplied(payload)))
    result = ops.get_theme()
    assert isinstance(result, OpError)
    assert result.code == "fault"


def test_get_window_settings_reads_all_four_fields() -> None:
    # The display owns and reports opacity, font_scale, decorated, and fps_idle.
    payload = {
        "opacity": 0.9,
        "font_scale": 1.25,
        "decorated": False,
        "fps_idle": 30.0,
    }
    ops = _ops(_FakePort(query=DisplayReplied(payload)))
    result = ops.get_window_settings()
    assert isinstance(result, WindowSettings)
    assert result.opacity == 0.9
    assert result.font_scale == 1.25
    assert result.decorated is False
    assert result.fps_idle == 30.0


def test_screenshot_asks_the_display_and_returns_the_path_it_painted() -> None:
    port = _FakePort(query=DisplayReplied({"path": "/tmp/lux-screenshots/a.png"}))

    result = _ops(port).screenshot()

    assert port.last_method == "screenshot"
    assert isinstance(result, Screenshot)
    assert result.path == "/tmp/lux-screenshots/a.png"


def test_screenshot_relays_the_displays_error() -> None:
    # The display answers a second request while one waits, or a failed GL read,
    # with an error sentence; that is the caller's answer, not a blank PNG.
    port = _FakePort(query=DisplayErrored("a screenshot is already waiting"))

    result = _ops(port).screenshot()

    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert "already waiting" in result.reason


def test_screenshot_without_a_path_in_the_reply_is_a_fault() -> None:
    port = _FakePort(query=DisplayReplied({}))

    result = _ops(port).screenshot()

    assert isinstance(result, OpError)
    assert result.code == "fault"


def test_ping_returns_elapsed_time() -> None:
    # The port measures rtt; this operation narrows the reply into a Pong.
    port = _FakePort(ping=DisplayReplied({"rtt_seconds": 0.05}))
    ops = _ops(port)
    result = ops.ping()
    assert isinstance(result, Pong)
    assert result.rtt_seconds == 0.05
    # The default wait is the absence contract — None threads to the port.
    assert port.last_wait is None


def test_ping_forwards_the_wait_to_the_port() -> None:
    # A bounded wait is not swallowed: it reaches the port as the display-leg
    # budget, so the REST timeout query param genuinely shortens the wait.
    port = _FakePort(ping=DisplayReplied({"rtt_seconds": 0.02}))
    _ops(port).ping(1.5)
    assert port.last_wait == 1.5


def test_set_frame_state_returns_ok_and_rejects_empty_patch() -> None:
    # The live reply shape: the frame acted on plus the fields the display flipped.
    port = _FakePort(
        query=DisplayReplied({"frame_id": "f1", "changed": {"minimized": True}})
    )
    ops = _ops(port)
    result = ops.set_frame_state("f1", FrameStatePatch.parse({"minimized": True}))
    assert isinstance(result, Ok)
    assert port.last_params == {"frame_id": "f1", "minimized": True}

    empty = ops.set_frame_state("f1", FrameStatePatch.parse({}))
    assert isinstance(empty, OpError)
    assert empty.code == "invalid_request"
    assert empty.reason == "no frame state provided"


def test_list_frames_reports_where_each_frame_is_shown() -> None:
    # The read that makes a docked frame observable from outside the display.
    # Docking is a visibility, not an erasure, so the frame the user minimized
    # is listed like any other -- a caller can tell it from a frame that never
    # existed by its presence, and this is where it learns the difference.
    port = _FakePort(
        query=DisplayReplied(
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
                    },
                    {
                        "frame_id": "f2",
                        "title": "Beads",
                        "scene_count": 1,
                        "scene_ids": ["s2"],
                        "layout": "tab",
                        "visibility": "on_screen",
                    },
                ],
            }
        )
    )

    result = _ops(port).list_frames()

    assert isinstance(result, FrameStates)
    assert [(f.frame_id, f.visibility) for f in result.frames] == [
        ("f1", "docked"),
        ("f2", "on_screen"),
    ]
    assert port.last_method == "list_scenes"


def test_list_frames_refuses_a_reply_it_does_not_recognise() -> None:
    # "The display answered with something I do not understand" and "the display
    # holds no frames" are different facts, and an empty list would conflate them.
    port = _FakePort(query=DisplayReplied({"frames": [{"frame_id": "f1"}]}))

    result = _ops(port).list_frames()

    assert isinstance(result, OpError)


def test_list_frames_passes_a_display_failure_through() -> None:
    """No display running is a fault the caller sees, never an empty frame list."""
    port = _FakePort(query=DisplayFault.UNAVAILABLE)

    result = _ops(port).list_frames()

    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"


def test_set_frame_state_faults_on_a_reply_missing_the_frame_id() -> None:
    # Schema drift must not fabricate success: a reply that does not acknowledge
    # the frame is a malformed display reply (fault), not an Ok. Both this and the
    # wrong-frame_id case below are faults, so the two ack failures are unified.
    port = _FakePort(query=DisplayReplied({"changed": {"minimized": True}}))
    ops = _ops(port)
    result = ops.set_frame_state("f1", FrameStatePatch.parse({"minimized": True}))
    assert isinstance(result, OpError)
    assert result.code == "fault"


def test_set_frame_state_faults_on_a_reply_acknowledging_a_different_frame() -> None:
    # The display acked a different frame than asked: the display did the wrong
    # thing, so this is a backend fault, not the engine refusing a caller write.
    port = _FakePort(query=DisplayReplied({"frame_id": "other", "changed": {}}))
    ops = _ops(port)
    result = ops.set_frame_state("f1", FrameStatePatch.parse({"minimized": True}))
    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert "f1" in result.reason
