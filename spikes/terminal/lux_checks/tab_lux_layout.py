"""Does Tab reach the program when the terminal is a child inside a parent window
that has other items (as in a Lux frame)? Headless ImGui, real view + PTY."""
import time
from imgui_bundle import ImVec2, imgui
from punt_lux.display.terminal.remote_sessions import RemoteSessions as TerminalSessions

imgui.create_context(); io = imgui.get_io(); io.display_size = ImVec2(1400, 900); io.delta_time = 1/60
io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
io.config_mac_osx_behaviors = True  # as on macOS
s = TerminalSessions.get("t", "/bin/bash --norc --noprofile -i")
sent = []
w = s.view.on_input
s.view.on_input = lambda d: (sent.append(d), w(d))
s.view.input._write = s.view.on_input

def frame():
    TerminalSessions.pump_all()
    imgui.new_frame()
    imgui.set_next_window_pos(ImVec2(0, 0)); imgui.set_next_window_size(ImVec2(1400, 900))
    imgui.begin("Lux frame")
    if imgui.begin_tab_bar("##frame_tabs"):            # as render_loop.py:684
        if imgui.begin_tab_item("terminal-demo")[0]:
            imgui.text("A markdown/text element above the terminal")
            s.view.render_in_child("##terminal-demo", ImVec2(0, 0))
            imgui.end_tab_item()
        imgui.end_tab_bar()
    imgui.end(); imgui.render()

try:
    for _ in range(30): frame(); time.sleep(0.01)
    io.add_mouse_pos_event(400, 400); frame(); io.add_mouse_button_event(0, True); frame(); io.add_mouse_button_event(0, False); frame()
    for ch in "cd ~/":
        io.add_input_character(ord(ch)); frame()
    before = len(sent)
    io.add_key_event(imgui.Key.tab, True); frame(); io.add_key_event(imgui.Key.tab, False); frame()
    for _ in range(20): frame(); time.sleep(0.01)
    tab_bytes = [d for d in sent[before:] if b"\t" in d]
    print("Tab reached program:", bool(tab_bytes), tab_bytes[:2])
    pass
finally:
    TerminalSessions.close_all()
