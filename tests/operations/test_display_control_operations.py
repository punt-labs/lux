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
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_info import DisplayInfo
from punt_lux.operations.models.display_probe import Pong, Screenshot
from punt_lux.operations.models.display_write import FrameStatePatch
from punt_lux.operations.models.menu_results import Ok
from punt_lux.operations.models.theme import SetThemeRequest, ThemeState
from punt_lux.operations.models.window import WindowSettings, WindowSettingsPatch

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

    def __new__(
        cls, *, query: DisplayReply | None = None, ping: DisplayReply | None = None
    ) -> Self:
        self = super().__new__(cls)
        self._query_reply = query if query is not None else DisplayReplied(payload={})
        self._ping_reply = ping if ping is not None else DisplayReplied(payload={})
        self._last_method = ""
        self._last_params = {}
        return self

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        self._last_method = method
        self._last_params = params
        return self._query_reply

    def ping(self, *, now: float) -> DisplayReply:
        return self._ping_reply

    @property
    def last_method(self) -> str:
        return self._last_method

    @property
    def last_params(self) -> Mapping[str, object]:
        return self._last_params


def test_get_display_info_accepts_the_live_display_payload() -> None:
    # The drift defect: the display's real 8-field payload must validate against
    # the model the MCP output schema is derived from.
    ops = DisplayControlOperations(_FakePort(query=DisplayReplied(_LIVE_DISPLAY_INFO)))
    result = ops.get_display_info()
    assert isinstance(result, DisplayInfo)
    assert result.backend == "OpenGL3"
    assert result.element_kinds == 25


def test_get_display_info_maps_unavailable_to_op_error() -> None:
    ops = DisplayControlOperations(
        _FakePort(query=DisplayFault(code="display_unavailable"))
    )
    result = ops.get_display_info()
    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"


def test_get_display_info_maps_timeout_to_op_error() -> None:
    ops = DisplayControlOperations(_FakePort(query=DisplayFault(code="timeout")))
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
    ops = DisplayControlOperations(_FakePort(query=DisplayReplied(payload)))
    result = ops.get_theme()
    assert isinstance(result, ThemeState)
    assert result.theme == "darcula"
    assert result.available == ["imgui_colors_light", "darcula", "gray_variations"]


def test_get_theme_rejects_an_unknown_theme_name() -> None:
    # An unrecognized theme name fails loudly rather than being silently dropped.
    payload = {"current": "not_a_theme", "available": []}
    ops = DisplayControlOperations(_FakePort(query=DisplayReplied(payload)))
    result = ops.get_theme()
    assert isinstance(result, OpError)
    assert result.code == "rejected"


def test_get_window_settings_reads_all_four_fields() -> None:
    # The display owns and reports opacity, font_scale, decorated, and fps_idle.
    payload = {
        "opacity": 0.9,
        "font_scale": 1.25,
        "decorated": False,
        "fps_idle": 30.0,
    }
    ops = DisplayControlOperations(_FakePort(query=DisplayReplied(payload)))
    result = ops.get_window_settings()
    assert isinstance(result, WindowSettings)
    assert result.opacity == 0.9
    assert result.font_scale == 1.25
    assert result.decorated is False
    assert result.fps_idle == 30.0


def test_screenshot_returns_path_then_maps_error() -> None:
    ok = DisplayControlOperations(
        _FakePort(query=DisplayReplied({"path": "/tmp/lux-x.png"}))
    )
    shot = ok.screenshot()
    assert isinstance(shot, Screenshot)
    assert shot.path == "/tmp/lux-x.png"

    errored = DisplayControlOperations(
        _FakePort(query=DisplayErrored(message="OpenGL not available"))
    )
    result = errored.screenshot()
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert result.reason == "OpenGL not available"


def test_ping_returns_elapsed_time() -> None:
    port = _FakePort(ping=DisplayReplied({"rtt_seconds": 0.05}))
    ops = DisplayControlOperations(port)
    result = ops.ping(now=1000.0)
    assert isinstance(result, Pong)
    assert result.rtt_seconds == 0.05


def test_set_theme_returns_the_new_theme_state_and_rejects_unknown() -> None:
    # The display replies with the new theme state (current + available); the
    # setter narrows it into a ThemeState, never a fabricated success.
    reply = {"current": "darcula", "available": ["imgui_colors_light", "darcula"]}
    port = _FakePort(query=DisplayReplied(reply))
    ops = DisplayControlOperations(port)
    state = ops.set_theme(SetThemeRequest.parse("darcula"))
    assert isinstance(state, ThemeState)
    assert state.theme == "darcula"
    assert port.last_method == "set_theme"
    assert port.last_params == {"theme": "darcula"}

    rejected = ops.set_theme(SetThemeRequest.parse("no_such_theme"))
    assert isinstance(rejected, OpError)
    assert rejected.code == "invalid_request"


def test_set_theme_rejects_a_malformed_reply_instead_of_fabricating_success() -> None:
    # A reply the ThemeState model does not recognize is an OpError(rejected),
    # never a success carrying the requested value.
    port = _FakePort(query=DisplayReplied({"current": "not_a_theme", "available": []}))
    ops = DisplayControlOperations(port)
    result = ops.set_theme(SetThemeRequest.parse("darcula"))
    assert isinstance(result, OpError)
    assert result.code == "rejected"


def test_set_window_settings_rejects_empty_patch() -> None:
    ops = DisplayControlOperations(_FakePort())
    result = ops.set_window_settings(WindowSettingsPatch.parse({}))
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert result.reason == "no settings provided"


def test_set_window_settings_rejects_out_of_range_opacity() -> None:
    # The patch validates against the documented bounds before any round-trip.
    ops = DisplayControlOperations(_FakePort())
    result = ops.set_window_settings(WindowSettingsPatch.parse({"opacity": 5.0}))
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"


def test_set_window_settings_returns_the_new_settings() -> None:
    reply = {
        "opacity": 0.5,
        "font_scale": 1.0,
        "decorated": True,
        "fps_idle": 10.0,
    }
    port = _FakePort(query=DisplayReplied(reply))
    ops = DisplayControlOperations(port)
    result = ops.set_window_settings(WindowSettingsPatch.parse({"opacity": 0.5}))
    assert isinstance(result, WindowSettings)
    assert result.opacity == 0.5
    assert port.last_params == {"opacity": 0.5}


def test_set_frame_state_returns_ok_and_rejects_empty_patch() -> None:
    port = _FakePort(query=DisplayReplied({"frame_id": "f1", "changed": {}}))
    ops = DisplayControlOperations(port)
    result = ops.set_frame_state("f1", FrameStatePatch.parse({"minimized": True}))
    assert isinstance(result, Ok)
    assert port.last_params == {"frame_id": "f1", "minimized": True}

    empty = ops.set_frame_state("f1", FrameStatePatch.parse({}))
    assert isinstance(empty, OpError)
    assert empty.code == "invalid_request"
    assert empty.reason == "no frame state provided"
