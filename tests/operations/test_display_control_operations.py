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
from punt_lux.operations.models.display_write import DisplayAck, FrameStatePatch
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


def test_get_theme_normalizes_qualified_enum_names() -> None:
    # The display enumerates available themes as qualified enum strings; the
    # operation normalizes them to bare names and drops any it does not know.
    payload = {
        "current": "darcula",
        "available": [
            "ImGuiTheme_.imgui_colors_light",
            "ImGuiTheme_.darcula",
            "ImGuiTheme_.some_unknown_theme",
        ],
    }
    ops = DisplayControlOperations(_FakePort(query=DisplayReplied(payload)))
    result = ops.get_theme()
    assert isinstance(result, ThemeState)
    assert result.theme == "darcula"
    assert result.available == ["imgui_colors_light", "darcula"]


def test_get_window_settings_fills_omitted_fields_with_display_defaults() -> None:
    # The display's getter reports only font_scale and fps_idle; opacity and
    # decorated fall back to the display's own initial state.
    payload = {"font_scale": 1.25, "fps_idle": 30.0}
    ops = DisplayControlOperations(_FakePort(query=DisplayReplied(payload)))
    result = ops.get_window_settings()
    assert isinstance(result, WindowSettings)
    assert result.font_scale == 1.25
    assert result.opacity == 1.0
    assert result.decorated is True


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


def test_set_theme_proxies_valid_theme_and_rejects_unknown() -> None:
    port = _FakePort(query=DisplayReplied({"theme": "darcula"}))
    ops = DisplayControlOperations(port)
    ack = ops.set_theme(SetThemeRequest.parse("darcula"))
    assert isinstance(ack, DisplayAck)
    assert port.last_method == "set_theme"
    assert port.last_params == {"theme": "darcula"}

    rejected = ops.set_theme(SetThemeRequest.parse("no_such_theme"))
    assert isinstance(rejected, OpError)
    assert rejected.code == "invalid_request"


def test_set_window_settings_rejects_empty_patch() -> None:
    ops = DisplayControlOperations(_FakePort())
    result = ops.set_window_settings(WindowSettingsPatch.parse({}))
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert result.reason == "no settings provided"


def test_set_window_settings_sends_only_provided_fields() -> None:
    port = _FakePort(query=DisplayReplied({"changed": {"opacity": 0.5}}))
    ops = DisplayControlOperations(port)
    ack = ops.set_window_settings(WindowSettingsPatch.parse({"opacity": 0.5}))
    assert isinstance(ack, DisplayAck)
    assert port.last_params == {"opacity": 0.5}


def test_set_frame_state_proxies_the_minimize_flag() -> None:
    port = _FakePort(query=DisplayReplied({"frame_id": "f1", "minimized": True}))
    ops = DisplayControlOperations(port)
    ack = ops.set_frame_state("f1", FrameStatePatch.parse({"minimized": True}))
    assert isinstance(ack, DisplayAck)
    assert port.last_params == {"frame_id": "f1", "minimized": True}
