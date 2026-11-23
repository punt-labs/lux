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
from imgui_bundle import imgui
from PIL import Image

from punt_lux.kernel.programmer_error import ProgrammerError
from punt_lux.wire.model import QueryResponse

if TYPE_CHECKING:
    from punt_lux.display.display_log import ErrorRecorder

logger = logging.getLogger(__name__)

__all__ = ["FramebufferCapture"]

_METHOD = "screenshot"


@final
class FramebufferCapture:
    """Read the OpenGL framebuffer into a PNG; answer the ``screenshot`` query."""

    _record_error: ErrorRecorder
    __slots__ = ("_record_error",)

    def __new__(cls, record_error: ErrorRecorder) -> Self:
        self = super().__new__(cls)
        self._record_error = record_error
        return self

    def capture(self) -> QueryResponse:
        """Capture the frame just swapped to the screen; a failure is an error reply.

        Runs on the render thread after the swap, so ``GL_FRONT`` holds the
        presented frame. The read is sized from the live framebuffer scale
        (``io.display_framebuffer_scale``, 2.0 on a Retina display): the
        ``final_app_window_screenshot_framebuffer_scale`` global is 1.0 until
        ``run()`` exits, and sizing from it reads one quarter of the buffer.
        """
        try:
            io = imgui.get_io()
            scale_x, scale_y = (
                io.display_framebuffer_scale.x,
                io.display_framebuffer_scale.y,
            )
            fb_width = int(io.display_size.x * scale_x)
            fb_height = int(io.display_size.y * scale_y)
            GL.glReadBuffer(GL.GL_FRONT)
            GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
            data = GL.glReadPixels(
                0, 0, fb_width, fb_height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE
            )
            image = Image.frombytes("RGBA", (fb_width, fb_height), bytes(data))
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            path = self._save(image)
        except ProgrammerError:
            raise
        except Exception as exc:  # the reply carries the failure
            logger.exception("Screenshot capture failed")
            self._record_error("error", str(exc), _METHOD)
            return QueryResponse(method=_METHOD, error=str(exc))
        return QueryResponse(method=_METHOD, result={"path": path})

    @staticmethod
    def _save(image: Image.Image) -> str:
        tmp_dir = Path(tempfile.gettempdir()) / "lux-screenshots"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(
            suffix=".png", prefix="lux-screenshot-", dir=tmp_dir
        )
        os.close(fd)
        image.save(path)
        return path
