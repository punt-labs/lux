# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""FramebufferCapture -- the PNG of what the display just painted."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

import OpenGL.GL as GL
from imgui_bundle import hello_imgui, imgui
from PIL import Image

from punt_lux.protocol import ScreenshotResponse

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = ["FramebufferCapture"]


@final
class FramebufferCapture:
    """Reads the OpenGL framebuffer into a PNG and says where it was saved."""

    _record_error: Callable[[str, str, str], None]
    __slots__ = ("_record_error",)

    def __new__(cls, record_error: Callable[[str, str, str], None]) -> Self:
        self = super().__new__(cls)
        self._record_error = record_error
        return self

    def capture(self) -> ScreenshotResponse:
        """Capture the framebuffer after a swap; a failure is an error response.

        Called after the buffer swap so GL_FRONT holds the fully rendered frame.
        Uses ``glReadPixels`` with the Retina scale factor.
        """
        try:
            scale = hello_imgui.final_app_window_screenshot_framebuffer_scale()
            io = imgui.get_io()
            fb_width = int(io.display_size.x * scale)
            fb_height = int(io.display_size.y * scale)
            GL.glReadBuffer(GL.GL_FRONT)
            GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
            data = GL.glReadPixels(
                0, 0, fb_width, fb_height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE
            )

            image = Image.frombytes("RGBA", (fb_width, fb_height), bytes(data))
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

            tmp_dir = Path(tempfile.gettempdir()) / "lux-screenshots"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            fd, path = tempfile.mkstemp(
                suffix=".png", prefix="lux-screenshot-", dir=str(tmp_dir)
            )
            os.close(fd)
            image.save(path)
        except Exception as exc:
            logger.exception("Screenshot capture failed")
            self._record_error("error", str(exc), "screenshot")
            return ScreenshotResponse(error=str(exc))
        return ScreenshotResponse(path=path)
