"""End-to-end frame cost: TerminalSessions.pump_all + paint, headless ImGui, real Ghostty views."""
import statistics, sys, time
from imgui_bundle import ImVec2, imgui
from punt_lux.display.terminal.font import TerminalFont
from punt_lux.display.terminal.sessions import TerminalSessions

FLOOD = "/bin/sh -c \"exec yes 'the quick brown fox jumps over the lazy dog 0123456789'\""
IDLE = "/bin/sh -c 'exec sleep 30'"
SCENARIOS = {"1 flood": [FLOOD], "2 floods": [FLOOD, FLOOD], "1 flood + 3 idle": [FLOOD, IDLE, IDLE, IDLE], "4 idle": [IDLE] * 4}

imgui.create_context(); io = imgui.get_io(); io.display_size = ImVec2(2000, 1200); io.delta_time = 1 / 60
io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
TerminalFont.load()
name = sys.argv[1]
sessions = [TerminalSessions.get(f"s{i}", cmd) for i, cmd in enumerate(SCENARIOS[name])]
try:
    frames, end = [], time.monotonic() + 3
    while time.monotonic() < end:
        t0 = time.monotonic()
        imgui.new_frame(); imgui.push_font(TerminalFont.font, TerminalFont.size)
        TerminalSessions.pump_all()
        for i, s in enumerate(sessions):
            imgui.set_next_window_pos(ImVec2(i * 480, 0)); imgui.set_next_window_size(ImVec2(470, 600))
            imgui.begin(f"w{i}"); s.view.render_in_child(f"t{i}"); imgui.end()
        imgui.pop_font(); imgui.render()
        frames.append((time.monotonic() - t0) * 1e3)
        time.sleep(max(0.0, 1 / 60 - (time.monotonic() - t0)))
    mb = sum(s.bytes_in for s in sessions) / 3 / 1e6
    p95 = sorted(frames)[int(len(frames) * 0.95)]
    print(f"{name:18s} {mb:6.1f} MB/s total   frame work p50 {statistics.median(frames):5.2f} ms  p95 {p95:5.2f} ms")
finally:
    TerminalSessions.close_all()
