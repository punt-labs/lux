# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""FramebufferCapture -- the frame the display is about to present, as an image."""

from __future__ import annotations

from typing import final

import OpenGL.GL as GL
from imgui_bundle import imgui
from PIL import Image

__all__ = ["FramebufferCapture"]


@final
class FramebufferCapture:
    """Read the drawn frame out of the back buffer.

    Runs on the render thread between ImGui's draw and the buffer swap, so
    ``GL_BACK`` holds the complete frame about to be presented. A read of
    ``GL_FRONT`` after the swap is blank on Mesa/GLX. The read is sized from
    the live framebuffer scale (``io.display_framebuffer_scale``, 2.0 on a
    Retina display); the ``final_app_window_screenshot_framebuffer_scale``
    global is 1.0 until ``run()`` exits and sizing from it reads one quarter of
    the buffer.
    """

    __slots__ = ()

    @staticmethod
    def read_frame() -> Image.Image:
        """Read the whole back buffer at the live framebuffer scale, top row first.

        Raises:
            Exception: whatever the GL binding or the image decode raises; the
                caller turns it into the query's error reply.
        """
        io = imgui.get_io()
        scale_x, scale_y = (
            io.display_framebuffer_scale.x,
            io.display_framebuffer_scale.y,
        )
        fb_width = int(io.display_size.x * scale_x)
        fb_height = int(io.display_size.y * scale_y)
        GL.glReadBuffer(GL.GL_BACK)
        GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
        data = GL.glReadPixels(
            0, 0, fb_width, fb_height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE
        )
        image = Image.frombytes("RGBA", (fb_width, fb_height), bytes(data))
        return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
