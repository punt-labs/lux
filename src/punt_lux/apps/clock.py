"""Analog Clock — smooth-sweeping clock face in a Lux frame.

Render-function-based applet for the Applications menu.  Uses ImGui
draw list for circle face, hour marks, and three hands (hour, minute,
second) with smooth animation via ``time.time()``.

Public API:
    CLOCK_SOURCE  — render function source string
    render_clock  — send the clock to a LuxClient
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.protocol import RenderFunctionElement

if TYPE_CHECKING:
    from punt_lux.client import LuxClient

CLOCK_SOURCE = """\
def render(ctx):
    import math
    import time
    from imgui_bundle import imgui

    radius = 50.0
    size = radius * 2 + 10
    imgui.dummy(imgui.ImVec2(size, size))

    draw = imgui.get_window_draw_list()
    pos = imgui.get_item_rect_min()
    cx = pos.x + size / 2
    cy = pos.y + size / 2

    # face
    white = imgui.get_color_u32(imgui.ImVec4(1, 1, 1, 0.8))
    gray = imgui.get_color_u32(imgui.ImVec4(0.6, 0.6, 0.6, 0.6))
    draw.add_circle(imgui.ImVec2(cx, cy), radius, white, 64, 1.5)

    # hour marks
    for i in range(12):
        angle = math.radians(i * 30 - 90)
        inner = radius * 0.85
        outer = radius * 0.95
        x1 = cx + math.cos(angle) * inner
        y1 = cy + math.sin(angle) * inner
        x2 = cx + math.cos(angle) * outer
        y2 = cy + math.sin(angle) * outer
        thick = 2.0 if i % 3 == 0 else 1.0
        p1 = imgui.ImVec2(x1, y1)
        p2 = imgui.ImVec2(x2, y2)
        draw.add_line(p1, p2, gray, thick)

    # time
    now = time.time()
    lt = time.localtime(now)
    frac_sec = now % 1.0
    seconds = lt.tm_sec + frac_sec
    minutes = lt.tm_min + seconds / 60.0
    hours = (lt.tm_hour % 12) + minutes / 60.0

    def hand(angle_deg, length, color_vec, thickness):
        angle = math.radians(angle_deg - 90)
        x = cx + math.cos(angle) * length
        y = cy + math.sin(angle) * length
        c = imgui.get_color_u32(color_vec)
        draw.add_line(imgui.ImVec2(cx, cy), imgui.ImVec2(x, y), c, thickness)

    # hour hand
    hand(hours * 30, radius * 0.5, imgui.ImVec4(1, 1, 1, 0.9), 3.0)
    # minute hand
    hand(minutes * 6, radius * 0.7, imgui.ImVec4(1, 1, 1, 0.9), 2.0)
    # second hand
    hand(seconds * 6, radius * 0.85, imgui.ImVec4(1, 0.3, 0.3, 0.9), 1.0)

    # center dot
    red = imgui.get_color_u32(imgui.ImVec4(1, 0.3, 0.3, 1))
    draw.add_circle_filled(imgui.ImVec2(cx, cy), 3, red)
"""


def render_clock(client: LuxClient) -> None:
    """Send the analog clock to the display via *client*.

    Uses ``show_async`` so the call is non-blocking (safe to call from
    a menu callback thread).
    """
    client.show_async(
        "app-clock",
        elements=[
            RenderFunctionElement(id="clock", source=CLOCK_SOURCE),
        ],
        frame_id="app-clock",
        frame_title="Clock",
        frame_size=(120, 120),
        frame_flags={
            "no_title_bar": True,
            "no_background": True,
            "auto_resize": True,
            "no_resize": True,
        },
    )
