# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Idle screen rendering — ambient flame animation and radial light rays."""

from __future__ import annotations

import time
from typing import Any


def draw_flame_shape(
    draw: Any,
    imgui: Any,
    base_x: float,
    base_y: float,
    tip_x: float,
    tip_y: float,
    width: float,
    height: float,
    *,
    r: float,
    g: float,
    b: float,
    alpha: float,
) -> None:
    """Draw a flame shape: rounded bulb at base tapering to a pointed tip."""
    from imgui_bundle import ImVec2

    color = imgui.get_color_u32((r, g, b, alpha))
    half_w = width

    bl = ImVec2(base_x - half_w, base_y)
    br = ImVec2(base_x + half_w, base_y)
    tip = ImVec2(tip_x, tip_y)

    kappa = 0.5522847498
    arc_cp = half_w * kappa

    draw.path_clear()
    draw.path_line_to(br)

    base_bottom = ImVec2(base_x, base_y + half_w * 0.5)
    draw.path_bezier_cubic_curve_to(
        ImVec2(br.x, base_y + arc_cp * 0.5),
        ImVec2(base_x + arc_cp, base_bottom.y),
        base_bottom,
    )
    draw.path_bezier_cubic_curve_to(
        ImVec2(base_x - arc_cp, base_bottom.y),
        ImVec2(bl.x, base_y + arc_cp * 0.5),
        bl,
    )
    draw.path_bezier_cubic_curve_to(
        ImVec2(base_x - half_w * 1.3, base_y - height * 0.35),
        ImVec2(tip_x - width * 0.08, tip_y + height * 0.25),
        tip,
    )
    draw.path_bezier_cubic_curve_to(
        ImVec2(tip_x + width * 0.08, tip_y + height * 0.25),
        ImVec2(base_x + half_w * 1.3, base_y - height * 0.35),
        br,
    )
    draw.path_fill_convex(color)


def render_idle(imgui: Any) -> None:
    """Render an ambient idle screen with radial light rays and flame.

    Always called -- the flame persists as a background element
    whether content is present or not.  Frames and scenes render
    on top since they are separate ImGui windows.
    """
    import math

    from imgui_bundle import ImVec2, ImVec4

    t = time.time()
    region = imgui.get_content_region_avail()
    origin = imgui.get_cursor_screen_pos()
    draw = imgui.get_window_draw_list()

    # Detect light vs dark theme from window background luminance
    bg = imgui.get_style_color_vec4(imgui.Col_.window_bg)
    bg_lum = bg.x * 0.299 + bg.y * 0.587 + bg.z * 0.114
    is_light = bg_lum > 0.5

    # -- radial light rays from center --
    cx = origin.x + region.x * 0.5
    cy = origin.y + region.y * 0.5
    max_radius = math.sqrt(region.x**2 + region.y**2) * 0.5
    num_rays = 48
    # Rays rotate very slowly with pauses
    rot_phase = math.sin(t * 0.15)
    rotation = rot_phase * rot_phase * rot_phase * 0.3  # radians, +/-0.3
    # Breathing modulates ray alpha
    breath_raw = math.sin(t * 0.8)
    ray_breath = max(breath_raw, 0.0) ** 0.6
    for i in range(num_rays):
        angle = (i / num_rays) * math.tau + rotation
        # Vary ray length and alpha for organic feel
        length_var = 0.6 + 0.4 * math.sin(angle * 3.0 + t * 0.2)
        ray_len = max_radius * length_var
        # Inner point (near flame, start offset to not overdraw flame)
        inner_r = 25.0
        ix = cx + math.cos(angle) * inner_r
        iy = cy + math.sin(angle) * inner_r
        # Outer point
        ox = cx + math.cos(angle) * ray_len
        oy = cy + math.sin(angle) * ray_len
        ray_alpha = (0.015 + 0.01 * ray_breath) * length_var
        # Dark theme: warm white rays; light theme: darker, more opaque rays
        if is_light:
            ray_col = imgui.get_color_u32(ImVec4(0.7, 0.4, 0.1, ray_alpha * 8.0))
        else:
            ray_col = imgui.get_color_u32(ImVec4(1.0, 0.7, 0.3, ray_alpha))
        draw.add_line(ImVec2(ix, iy), ImVec2(ox, oy), ray_col, 1.0)

    # -- centered flame (cx, cy already set above) --
    breath = ray_breath  # reuse breathing from rays

    # Flame sway: gentle tip movement with pauses
    sway_phase = math.sin(t * 0.6)
    sway = sway_phase * sway_phase * sway_phase * 3.0  # +/-3px, pauses at center
    # Secondary faster flicker for organic feel
    flicker = math.sin(t * 2.3) * 0.8 + math.sin(t * 3.7) * 0.4

    flame_h = 26.0 + 4.0 * breath  # flame height breathes
    flame_w = 10.0 + 1.5 * breath  # flame width breathes

    # Flame base center (bottom of flame)
    base_y = cy + 8.0
    tip_y = base_y - flame_h
    tip_x = cx + sway

    # -- outer glow (warm orange, very transparent) --
    glow_r = flame_w + 6.0
    glow_alpha = 0.06 + 0.03 * breath
    for i in range(3):
        r = glow_r + i * 4.0
        a = glow_alpha * (1.0 - i * 0.3)
        glow_col = imgui.get_color_u32(ImVec4(1.0, 0.6, 0.2, a))
        draw.add_circle_filled(ImVec2(cx, base_y - flame_h * 0.4), r, glow_col)

    # -- outer flame (deep orange) --
    draw_flame_shape(
        draw,
        imgui,
        cx,
        base_y,
        tip_x,
        tip_y,
        flame_w,
        flame_h,
        r=1.0,
        g=0.45,
        b=0.1,
        alpha=0.35 + 0.1 * breath,
    )

    # -- middle flame (bright orange-yellow) --
    mid_w = flame_w * 0.65
    mid_h = flame_h * 0.75
    mid_tip_y = base_y - mid_h
    draw_flame_shape(
        draw,
        imgui,
        cx,
        base_y,
        tip_x + flicker * 0.5,
        mid_tip_y,
        mid_w,
        mid_h,
        r=1.0,
        g=0.7,
        b=0.15,
        alpha=0.45 + 0.1 * breath,
    )

    # -- inner core (bright yellow-white) --
    core_w = flame_w * 0.3
    core_h = flame_h * 0.45
    core_tip_y = base_y - core_h
    draw_flame_shape(
        draw,
        imgui,
        cx,
        base_y + 2,
        tip_x + flicker * 0.3,
        core_tip_y + 2,
        core_w,
        core_h,
        r=1.0,
        g=0.95,
        b=0.7,
        alpha=0.55 + 0.15 * breath,
    )

    # "Ready" label below the flame -- uses theme text color at low alpha
    label_y = base_y + 10.0
    text = "Lux"
    text_size = imgui.calc_text_size(text)
    tc = imgui.get_style_color_vec4(imgui.Col_.text)
    text_color = imgui.get_color_u32(ImVec4(tc.x, tc.y, tc.z, 0.35))
    draw.add_text(ImVec2(cx - text_size.x * 0.5, label_y), text_color, text)
