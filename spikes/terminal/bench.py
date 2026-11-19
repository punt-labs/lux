"""Step 1 benchmark: replay recordings through each engine in a headless ImGui frame.

Per frame we time three phases separately:
  feed    -- parse the frame's bytes into terminal state
  prepare -- sync render state, rebuild dirty rows (ghostty only)
  draw    -- emit ImDrawList calls for the visible grid
Frame time = feed + prepare + draw (Python-side cost the Lux loop would pay).

usage: uv run python bench.py [--budget BYTES] [--engines ghostty,pyte] [names...]
"""

from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import dataclass, field

from imgui_bundle import ImVec2, imgui

import engines
import replay

FONT = ".venv/lib/python3.13/site-packages/imgui_bundle/assets/fonts/Inconsolata-Medium.ttf"
ALL = ["vim", "top", "ls_color", "unicode", "truecolor", "cat_source", "yes"]


@dataclass
class Stats:
    feed: list[float] = field(default_factory=list)
    prep: list[float] = field(default_factory=list)
    draw: list[float] = field(default_factory=list)
    total: list[float] = field(default_factory=list)
    rebuilt: list[int] = field(default_factory=list)
    vtx: list[int] = field(default_factory=list)


def setup_imgui(cols: int, rows: int) -> imgui.ImFont:
    imgui.create_context()
    io = imgui.get_io()
    io.display_size = ImVec2(cols * 12 + 100, rows * 20 + 100)
    io.delta_time = 1 / 60
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
    io.set_ini_filename("")
    return io.fonts.add_font_from_file_ttf(FONT, 15.0)


def run_one(eng_name: str, rec: replay.Recording, budget: int, max_frames: int) -> Stats:
    font = setup_imgui(rec.cols, rec.rows)
    eng = engines.make(eng_name, rec.cols, rec.rows)
    st = Stats()
    pc = time.perf_counter
    for batch in replay.frames(rec, budget, max_frames):
        imgui.new_frame()
        imgui.push_font(font, 15.0)
        imgui.set_next_window_pos(ImVec2(0, 0))
        imgui.set_next_window_size(imgui.get_io().display_size)
        imgui.begin("term", None, imgui.WindowFlags_.no_decoration.value)
        cw, ch = imgui.calc_text_size("M").x, imgui.get_text_line_height()
        t0 = pc()
        eng.feed(batch)
        t1 = pc()
        rebuilt = eng.prepare()
        t2 = pc()
        eng.draw(cw, ch)
        t3 = pc()
        imgui.end()
        imgui.pop_font()
        imgui.render()
        st.feed.append((t1 - t0) * 1e3)
        st.prep.append((t2 - t1) * 1e3)
        st.draw.append((t3 - t2) * 1e3)
        st.total.append((t3 - t0) * 1e3)
        st.rebuilt.append(rebuilt)
        st.vtx.append(imgui.get_draw_data().total_vtx_count)
    imgui.destroy_context()
    return st


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(p / 100 * len(s)))] if s else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=256 * 1024)
    ap.add_argument("--engines", default="ghostty,pyte")
    ap.add_argument("--max-frames", type=int, default=600)
    ap.add_argument("names", nargs="*", default=ALL)
    a = ap.parse_args()
    hdr = (
        f"{'recording':11} {'engine':7} {'frames':>6} {'MB':>6} {'MB/s':>7} "
        f"{'feed p50':>8} {'prep p50':>8} {'draw p50':>8} "
        f"{'tot p50':>7} {'tot p95':>7} {'tot max':>7} {'rows/f':>6} {'vtx':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for name in a.names:
        rec = replay.load(name)
        for eng in a.engines.split(","):
            st = run_one(eng, rec, a.budget, a.max_frames)
            n = len(st.total)
            fed_mb = min(rec.total_bytes, n * a.budget) / 1e6
            busy = [t for t in st.total if t > 0]
            mbps = fed_mb / (sum(st.feed) / 1e3) if sum(st.feed) else 0.0
            rebuilt = [r for r in st.rebuilt if r >= 0]
            print(
                f"{name:11} {eng:7} {n:6d} {fed_mb:6.2f} {mbps:7.1f} "
                f"{statistics.median(st.feed):8.2f} {statistics.median(st.prep):8.2f} "
                f"{statistics.median(st.draw):8.2f} {statistics.median(busy):7.2f} "
                f"{pct(busy, 95):7.2f} {max(busy):7.2f} "
                f"{(statistics.mean(rebuilt) if rebuilt else float('nan')):6.1f} "
                f"{max(st.vtx):7d}"
            )


if __name__ == "__main__":
    main()
