"""Which characters of a sample can the font stack draw? (no window needed)

Builds the same font stack as demo.py (Inconsolata + DejaVu [+ CJK/emoji
fallbacks]) in a headless ImGui context and asks the baked font for each
codepoint without fallback. Also reports glyph advance in cells, since wide
characters must fill exactly 2 cells.
"""

from __future__ import annotations

import sys

from imgui_bundle import ImVec2, imgui

import demo

SAMPLE = "日本語のテキスト 中文字符 한국어 🙂🚀👍🏽 👨‍👩‍👧 ✓ ★ │├─┤ λ→∞ café"


def check(with_fallbacks: bool, size: float = 15.0) -> None:
    imgui.create_context()
    io = imgui.get_io()
    io.display_size = ImVec2(800, 600)
    io.delta_time = 1 / 60
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
    mono = io.fonts.add_font_from_file_ttf(str(demo.ASSETS / "fonts/Inconsolata-Medium.ttf"), size)
    cfg = imgui.ImFontConfig()
    cfg.merge_mode = True
    io.fonts.add_font_from_file_ttf(str(demo.LUX_FONTS / "dejavu/DejaVu-Regular.ttf"), size, cfg)
    if with_fallbacks:
        for path, color in demo.FALLBACKS:
            c = imgui.ImFontConfig()
            c.merge_mode = True
            if color:
                c.font_loader_flags = 1 << 8
            io.fonts.add_font_from_file_ttf(path, size, c)
    imgui.new_frame()
    imgui.push_font(mono, size)
    fb = imgui.get_font_baked()
    cell = fb.find_glyph(ord("M")).advance_x
    missing: list[str] = []
    narrow_wide: list[str] = []
    for ch in dict.fromkeys(SAMPLE.replace(" ", "").replace("\u200d", "")):
        g = fb.find_glyph_no_fallback(ord(ch))
        if g is None:
            missing.append(ch)
        elif ord(ch) >= 0x2E80 and abs(g.advance_x / cell - 2) > 0.25:
            narrow_wide.append(f"{ch}({g.advance_x / cell:.2f} cells)")
    imgui.pop_font()
    imgui.end_frame()
    imgui.destroy_context()
    label = "with CJK+emoji fallbacks" if with_fallbacks else "Inconsolata + DejaVu only"
    print(f"{label}: missing {len(missing)}: {' '.join(missing) or '-'}")
    if narrow_wide:
        print(f"   wide chars not 2 cells wide: {' '.join(narrow_wide)}")


if __name__ == "__main__":
    check(False)
    check(True)
    sys.exit(0)
