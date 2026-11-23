"""FramebufferCapture reads the whole Retina back buffer, not a 1x corner of it."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import OpenGL.GL as GL
import pytest

from punt_lux.display.framebuffer_capture import FramebufferCapture

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


def test_the_read_covers_the_whole_framebuffer_at_the_live_retina_scale() -> None:
    """The exit-only scale global reads 1.0 while the app runs; the live scale is io's.

    Reading a 1x rectangle out of a 2x buffer captures the bottom-left quarter,
    where no widget is: the "chrome but no widgets" DES-028 recorded.
    """
    with (
        patch("punt_lux.display.framebuffer_capture.imgui.get_io", lambda: _io(_SCALE)),
        patch(
            "imgui_bundle.hello_imgui.final_app_window_screenshot_framebuffer_scale",
            lambda: 1.0,
        ),
        patch("punt_lux.display.framebuffer_capture.GL.glReadBuffer") as read_buffer,
        patch("punt_lux.display.framebuffer_capture.GL.glPixelStorei"),
        patch("punt_lux.display.framebuffer_capture.GL.glReadPixels", _red_pixels),
    ):
        frame = FramebufferCapture.read_frame()

    assert frame.size == (int(_W * _SCALE), int(_H * _SCALE))
    # Before the swap the drawn frame is in the back buffer; GL_FRONT is the
    # previous frame, and on Mesa/GLX reads blank.
    read_buffer.assert_called_once_with(GL.GL_BACK)


def test_a_failed_read_raises_for_the_caller_to_answer() -> None:
    with (
        patch("punt_lux.display.framebuffer_capture.imgui.get_io", lambda: _io(1.0)),
        patch(
            "punt_lux.display.framebuffer_capture.GL.glReadBuffer",
            side_effect=RuntimeError("no GL context"),
        ),
        pytest.raises(RuntimeError, match="no GL context"),
    ):
        FramebufferCapture.read_frame()
