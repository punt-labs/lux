"""zsh -l (the demo's command): does 'cd ~/' + Tab complete? Same view/PTY code, headless."""
import time
from imgui_bundle import ImVec2, imgui
from punt_lux.display.terminal.remote_sessions import RemoteSessions as TerminalSessions

imgui.create_context(); io = imgui.get_io(); io.display_size = ImVec2(1400, 900); io.delta_time = 1/60
io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
io.config_mac_osx_behaviors = True
s = TerminalSessions.get("z", "/bin/zsh -l")

def frame():
    TerminalSessions.pump_all()
    imgui.new_frame(); imgui.set_next_window_pos(ImVec2(0, 0)); imgui.set_next_window_size(ImVec2(1400, 900))
    imgui.begin("Lux frame")
    if imgui.begin_tab_bar("##t"):
        if imgui.begin_tab_item("demo")[0]:
            s.view.render_in_child("##term", ImVec2(0, 0)); imgui.end_tab_item()
        imgui.end_tab_bar()
    imgui.end(); imgui.render()

def run(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end: frame(); time.sleep(0.01)

try:
    run(3.0)  # let zsh start (compinit can be slow)
    io.add_mouse_pos_event(400, 400); frame(); io.add_mouse_button_event(0, True); frame(); io.add_mouse_button_event(0, False); frame()
    for ch in "cd ~/":
        io.add_input_character(ord(ch)); frame()
    run(0.3)
    print("before Tab:", repr(s.view.term.text().rstrip().splitlines()[-1][-40:]))
    io.add_key_event(imgui.Key.tab, True); frame(); io.add_key_event(imgui.Key.tab, False); frame()
    run(1.5)
    lines = s.view.term.text().rstrip().splitlines()
    print("after Tab: ", repr(lines[-1][-60:]))
    print("lines on screen after Tab:", len(lines))
finally:
    TerminalSessions.close_all()
