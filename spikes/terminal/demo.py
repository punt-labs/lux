"""Step 2 demo: Ghostty view vs the pyte TerminalView, side by side, in plain imgui-bundle.

usage:
  uv run python demo.py                      # live shell in both panes
  uv run python demo.py --replay top         # replay a recording in both panes
  uv run python demo.py --only ghostty -- vim  # one pane, a specific program
  uv run python demo.py --screenshot out.png --frames 90 --replay unicode

Lux-like constraints: one thread, zero-timeout select() per frame, hello_imgui
DarculaDarker theme, fps_idle 30 (wakes on input; PTY output does NOT wake it --
that is one of the things this demo shows).
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from imgui_bundle import ImVec2, hello_imgui, imgui, immapp

from ghostty_view import GhosttyTerminalView
from transport import LocalPtyTransport, ReplayTransport, ShowcaseTransport, Transport

ASSETS = Path(__file__).parent / ".venv/lib/python3.13/site-packages/imgui_bundle/assets"
LUX_FONTS = Path(__file__).parents[2] / "src/punt_lux/display/fonts"
FALLBACKS = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", False),  # CJK (zh + ja kana)
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", False),  # Hangul
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", False),  # λ ★ and misc
    ("/System/Library/Fonts/Apple Color Emoji.ttc", True),  # color emoji (sbix)
]


@dataclass
class Pane:
    name: str
    view: Any  # GhosttyTerminalView | imgui_terminal.TerminalView
    transport: Transport
    times: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    bytes_in: int = 0


def make_pane(kind: str, args: argparse.Namespace) -> Pane:
    t: Transport
    if args.showcase:
        t = ShowcaseTransport(args.showcase.split(","), seconds=args.seconds)
    elif args.replay:
        t = ReplayTransport(args.replay, budget=args.budget)
    else:
        t = LocalPtyTransport(args.cmd or None, budget=args.budget)
    # replays honour --fixed (the recording's 200x60); otherwise both widgets fit the pane,
    # as they do live -- programs recorded at 200x60 then wrap/clip like a real resize
    fixed = args.fixed and isinstance(t, (ReplayTransport, ShowcaseTransport))
    size = (200, 60) if fixed else (80, 24)
    if kind == "ghostty":
        v: Any = GhosttyTerminalView(*size, fixed=fixed)
    else:
        from imgui_bundle.imgui_terminal import TerminalView

        v = TerminalView(*size)
        if fixed:
            v._maybe_resize = lambda c, r: None  # keep the recording's size
    v.on_input = t.write
    v.on_resize = t.resize
    return Pane(kind, v, t)


class App:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        kinds = [args.only] if args.only else ["ghostty", "pyte"]
        self.panes = [make_pane(k, args) for k in kinds]
        self.mono: imgui.ImFont | None = None
        self.frame = 0
        self.frame_ms: deque[float] = deque(maxlen=120)
        self.gaps: list[float] = []
        self._last_output = 0.0
        self._last = time.perf_counter()

    def load_fonts(self) -> None:
        hello_imgui.imgui_default_settings.load_default_font_with_font_awesome_icons()
        params = hello_imgui.FontLoadingParams()
        params.inside_assets = False
        mono = ASSETS / "fonts/Inconsolata-Medium.ttf"
        self.mono = hello_imgui.load_font(str(mono), self.args.font_size, params)
        # merge DejaVu (Lux's font) for box drawing, arrows, accents Inconsolata lacks
        merge = hello_imgui.FontLoadingParams()
        merge.inside_assets = False
        merge.merge_to_last_font = True
        dejavu = LUX_FONTS / "dejavu/DejaVu-Regular.ttf"
        if dejavu.exists():
            hello_imgui.load_font(str(dejavu), self.args.font_size, merge)
        if self.args.cjk_emoji:
            self._merge_fallbacks()

    def _merge_fallbacks(self) -> None:
        """Merge CJK and color-emoji system fonts into the mono font, via ImGui directly.

        (hello_imgui.load_font's merge did not take effect for these in step 2.)
        FreeType flag LoadColor = 1 << 8 (imgui_freetype.h) renders sbix/CBDT color emoji.
        """
        io = imgui.get_io()
        for path, color in FALLBACKS:
            if not Path(path).exists():
                print("missing fallback font", path)
                continue
            cfg = imgui.ImFontConfig()
            cfg.merge_mode = True
            if color:
                cfg.font_loader_flags = 1 << 8
            io.fonts.add_font_from_file_ttf(path, self.args.font_size, cfg)

    def gui(self) -> None:
        now = time.perf_counter()
        self.frame_ms.append((now - self._last) * 1e3)
        if self.frame > self.args.warmup:
            self.gaps.append((now - self._last) * 1e3)
        self._last = now
        busy = False
        for p in self.panes:  # Lux-style: pump every transport once per frame
            data = p.transport.pump()
            p.bytes_in += len(data)
            p.view.feed(data)
            busy |= bool(data)
        if self.args.wake_on_output:
            # output arrived: keep full frame rate for a moment (like user input does)
            fps = hello_imgui.get_runner_params().fps_idling
            fps.enable_idling = not busy and (now - self._last_output > 0.25)
            if busy:
                self._last_output = now
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(vp.work_pos)
        imgui.set_next_window_size(vp.work_size)
        flags = imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_saved_settings
        imgui.begin("spike", None, flags)
        dt = statistics.mean(self.frame_ms) if self.frame_ms else 0.0
        hint = "click a pane to focus; Shift+PgUp/PgDn scrolls; Cmd/Ctrl+Shift+C/V copy/paste"
        now_showing = getattr(self.panes[0].transport, "current", None)
        label = f"NOW SHOWING: {now_showing}   " if now_showing else ""
        imgui.text(f"{label}frame {dt:5.1f} ms ({1000 / max(dt, 1e-3):4.0f} fps)   {hint}")
        avail = imgui.get_content_region_avail()
        w = (avail.x - imgui.get_style().item_spacing.x * (len(self.panes) - 1)) / len(self.panes)
        for i, p in enumerate(self.panes):
            if i:
                imgui.same_line()
            imgui.begin_group()
            ms = statistics.median(p.times) if p.times else 0.0
            title = getattr(p.view, "title", "") or ""
            imgui.text(f"{p.name}: {ms:5.2f} ms/frame  in {p.bytes_in / 1e6:6.2f} MB  {title[:40]}")
            assert self.mono is not None
            imgui.push_font(self.mono, self.args.font_size)
            t0 = time.perf_counter()
            p.view.render_in_child(f"term_{p.name}", ImVec2(w, avail.y - imgui.get_frame_height()))
            p.times.append((time.perf_counter() - t0) * 1e3)
            imgui.pop_font()
            imgui.end_group()
        imgui.end()
        self.frame += 1
        if self.args.frames and self.frame >= self.args.frames:
            hello_imgui.get_runner_params().app_shall_exit = True
        if not any(p.transport.alive for p in self.panes):
            hello_imgui.get_runner_params().app_shall_exit = True

    def report(self) -> None:
        if self.gaps:
            g = sorted(self.gaps)
            p50, p95 = g[len(g) // 2], g[int(len(g) * 0.95)]
            print(f"frame interval p50 {p50:5.1f} ms  p95 {p95:5.1f} ms  (n={len(g)})")
        for p in self.panes:
            ts = sorted(p.times)
            if ts:
                print(f"{p.name:8} render p50 {ts[len(ts) // 2]:6.2f} ms  "
                      f"p95 {ts[int(len(ts) * 0.95)]:6.2f} ms  max {ts[-1]:6.2f} ms")  # fmt: skip
            p.transport.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay")
    ap.add_argument("--showcase", help="comma-separated recordings to cycle through")
    ap.add_argument("--fixed", action="store_true", help="replay at the recorded 200x60")
    ap.add_argument("--seconds", type=float, default=12.0, help="showcase: seconds each")
    ap.add_argument("--only", choices=["ghostty", "pyte"])
    ap.add_argument("--budget", type=int, default=256 * 1024)
    ap.add_argument("--font-size", type=float, default=15.0)
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--warmup", type=int, default=0, help="frames to skip in the interval stats")
    ap.add_argument("--screenshot")
    ap.add_argument("--size", default="1600x900")
    ap.add_argument("--idle-after", type=float, default=3.0)
    ap.add_argument("--wake-on-output", action="store_true")
    ap.add_argument("--cjk-emoji", action="store_true", help="merge system CJK + emoji fonts")
    ap.add_argument("cmd", nargs="*")
    args = ap.parse_args()
    app = App(args)
    rp = hello_imgui.RunnerParams()
    rp.app_window_params.window_title = "Lux terminal spike — step 2"
    w, h = (int(x) for x in args.size.split("x"))
    rp.app_window_params.window_geometry.size = (w, h)
    rp.imgui_window_params.tweaked_theme.theme = hello_imgui.ImGuiTheme_.darcula_darker
    rp.callbacks.load_additional_fonts = app.load_fonts
    rp.callbacks.show_gui = app.gui
    rp.fps_idling.fps_idle = 30.0  # same as Lux
    rp.fps_idling.time_active_after_last_event = args.idle_after  # hello_imgui default 3 s
    rp.ini_disable = True
    if args.screenshot:

        def save() -> None:
            img = hello_imgui.final_app_window_screenshot()
            from PIL import Image

            Image.fromarray(img).save(args.screenshot)
            print("screenshot ->", args.screenshot)

        rp.callbacks.before_exit = save
    immapp.run(rp)
    app.report()


if __name__ == "__main__":
    main()
