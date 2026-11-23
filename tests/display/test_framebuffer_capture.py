"""FramebufferCapture reads the whole Retina framebuffer, not a 1x corner of it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

from PIL import Image

from punt_lux.display.framebuffer_capture import FramebufferCapture
from punt_lux.wire.model import QueryResponse

if TYPE_CHECKING:
    import pytest

    from punt_lux.display.display_log import ErrorSeverity

_W, _H, _SCALE = 48, 32, 2.0  # 48x32 points on a 2x display: 96x64 pixels


def _io(scale: float) -> SimpleNamespace:
    return SimpleNamespace(
        display_size=SimpleNamespace(x=_W, y=_H),
        display_framebuffer_scale=SimpleNamespace(x=scale, y=scale),
    )


def _red_pixels(x: int, y: int, w: int, h: int, *_args: object) -> bytes:
    # The "framebuffer" is red everywhere; the read window is what is tested.
    assert (x, y) == (0, 0)
    return bytes([255, 0, 0, 255]) * (w * h)


type _Recorded = tuple[ErrorSeverity, str, str]


def _recorder(into: list[_Recorded]) -> Callable[[ErrorSeverity, str, str], None]:
    def record(severity: ErrorSeverity, message: str, context: str) -> None:
        into.append((severity, message, context))

    return record


def _capture(tmp_path: Path, *, io_scale: float, exit_scale: float) -> QueryResponse:
    errors: list[_Recorded] = []
    with (
        patch(
            "punt_lux.display.framebuffer_capture.imgui.get_io", lambda: _io(io_scale)
        ),
        patch(
            "imgui_bundle.hello_imgui.final_app_window_screenshot_framebuffer_scale",
            lambda: exit_scale,
        ),
        patch("punt_lux.display.framebuffer_capture.GL.glReadBuffer"),
        patch("punt_lux.display.framebuffer_capture.GL.glPixelStorei"),
        patch("punt_lux.display.framebuffer_capture.GL.glReadPixels", _red_pixels),
        patch(
            "punt_lux.display.framebuffer_capture.tempfile.gettempdir",
            lambda: str(tmp_path),
        ),
    ):
        capture = FramebufferCapture(_recorder(errors))
        return capture.capture()


def test_the_read_covers_the_whole_framebuffer_at_the_live_retina_scale(
    tmp_path: Path,
) -> None:
    """The exit-only scale global reads 1.0 while the app runs; the live scale is io's.

    Reading a 1x rectangle out of a 2x buffer captures the bottom-left quarter,
    where no widget is: the "chrome but no widgets" DES-028 recorded.
    """
    response = _capture(tmp_path, io_scale=_SCALE, exit_scale=1.0)

    assert response.error is None, response.error
    with Image.open(response.result["path"]) as shot:
        assert shot.size == (int(_W * _SCALE), int(_H * _SCALE))


def test_a_capture_answers_the_screenshot_query(tmp_path: Path) -> None:
    response = _capture(tmp_path, io_scale=1.0, exit_scale=1.0)

    assert response.method == "screenshot"
    assert response.error is None
    assert Path(response.result["path"]).is_file()


def test_a_failed_read_is_an_error_response_and_is_recorded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    recorded: list[_Recorded] = []
    with (
        patch("punt_lux.display.framebuffer_capture.imgui.get_io", lambda: _io(1.0)),
        patch(
            "punt_lux.display.framebuffer_capture.GL.glReadBuffer",
            side_effect=RuntimeError("no GL context"),
        ),
    ):
        response = FramebufferCapture(_recorder(recorded)).capture()

    assert response.method == "screenshot"
    assert response.error == "no GL context"
    assert recorded == [("error", "no GL context", "screenshot")]
