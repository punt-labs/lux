"""Exploratory OS-input/table harness: NOT a passing acceptance check.

The recorded run renders the terminal and 1,000-row table, but PID-targeted
keyboard posting does not produce the warm response. No latency claim follows.
No system-wide keyboard posting fallback. Requires LUX_CAPTURE_SCRIPT and
macOS permissions; wrap a manual diagnostic rerun in timeout 120.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import shlex
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.protocol.pty.session_requests import KillRequest
from punt_lux.terminal.snapshot import snapshot_version
from spikes.terminal.check_two_windows import WindowProof
from tests.ptyd.wire_client import WireClient

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = """
import json,os,sys,threading,time
from pathlib import Path
root=Path(sys.argv[1]); lock=threading.Lock(); markers=[]; esc=chr(27)
def emit(data):
    with lock:
        os.write(1,data.encode())
def paint_ack():
    emit(esc+'7'+esc+'[1;1H'+esc+'[2K'+'ACK:'+markers[-1]+esc+'8')
def burst():
    (root/'started').write_text('yes')
    rows=os.get_terminal_size(1).lines
    emit(esc+'[2;'+str(rows)+'r'+esc+'[2;1H')
    chunk=('x'*79+'\\n')*204
    for _ in range(514):
        emit(chunk); time.sleep(.005)
    emit('\\r\\nBURST_DONE\\r\\n')
    paint_ack()
    (root/'done').write_text('yes')
emit('KEYBOARD_READY\\r\\n')
for line in sys.stdin:
    marker=line.strip(); stamp=time.monotonic_ns(); markers.append(marker)
    with open(root/'responses.jsonl','a') as output:
        output.write(json.dumps({'marker':marker,'time_ns':stamp})+'\\n')
    paint_ack()
    if marker=='burst':
        threading.Thread(target=burst).start()
"""


class KeyboardProof:
    @staticmethod
    def enter(q: Any, pid: int, text: str) -> int:
        for char in text:
            down = q.CGEventCreateKeyboardEvent(None, 0, True)
            q.CGEventKeyboardSetUnicodeString(down, 1, char)
            q.CGEventPostToPid(pid, down)
            time.sleep(0.025)
            up = q.CGEventCreateKeyboardEvent(None, 0, False)
            q.CGEventKeyboardSetUnicodeString(up, 1, char)
            q.CGEventPostToPid(pid, up)
            time.sleep(0.025)
        down = q.CGEventCreateKeyboardEvent(None, 36, True)
        sent = time.monotonic_ns()
        q.CGEventPostToPid(pid, down)
        time.sleep(0.025)
        q.CGEventPostToPid(pid, q.CGEventCreateKeyboardEvent(None, 36, False))
        return sent

    @staticmethod
    def responses(root: Path) -> dict[str, int]:
        path = root / "responses.jsonl"
        if not path.exists():
            return {}
        result: dict[str, int] = {}
        for line in path.read_text().splitlines():
            if line.endswith("}"):
                item = json.loads(line)
                result[item["marker"]] = item["time_ns"]
        return result

    @staticmethod
    def summary(values: list[float]) -> dict[str, object]:
        return {
            "samples": len(values),
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(sorted(values)[math.ceil(0.95 * len(values)) - 1], 3),
            "max_ms": round(max(values), 3),
        }

    @staticmethod
    def main() -> None:
        spec = importlib.util.spec_from_file_location(
            "capture", Path(os.environ["LUX_CAPTURE_SCRIPT"]).resolve()
        )
        assert spec is not None and spec.loader is not None
        capture: Any = importlib.util.module_from_spec(spec)
        sys.modules["capture"] = capture
        spec.loader.exec_module(capture)
        q = capture._quartz()
        assert q.CGPreflightPostEventAccess(), "event-posting permission not granted"
        original_mouse = q.CGEventGetLocation(q.CGEventCreate(None))
        processes: list[subprocess.Popen[bytes]] = []
        report: dict[str, object] = {}
        with (
            tempfile.TemporaryDirectory(prefix="lxkey-", dir="/tmp") as directory,
            ExitStack() as logs,
        ):
            root = Path(directory)
            pty = root / "pty" / "p.sock"
            display_path = root / "d.sock"
            env = dict(
                os.environ,
                HOME=str(root),
                LUX_SOCKET=str(display_path),
                LUX_PTY_SOCKET=str(pty),
                LUX_LOG_LEVEL="INFO",
            )

            def start(binary: str, *args: str) -> subprocess.Popen[bytes]:
                log = logs.enter_context(open(root / f"{binary}-{len(processes)}.log", "wb"))
                process = subprocess.Popen(
                    [str(ROOT / ".venv/bin" / binary), *args],
                    cwd=root,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                processes.append(process)
                return process

            def cli(*args: str) -> str:
                result = subprocess.run(
                    [str(ROOT / ".venv/bin/lux"), *args],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                assert result.returncode == 0, (result.stdout, result.stderr)
                return result.stdout

            def measure(display: subprocess.Popen[bytes], marker: str) -> float:
                assert display.poll() is None
                sent = KeyboardProof.enter(q, display.pid, marker)
                WindowProof.wait(lambda: marker in KeyboardProof.responses(root))
                elapsed = (KeyboardProof.responses(root)[marker] - sent) / 1_000_000
                assert elapsed >= 0
                return elapsed

            try:
                start("luxd-hub", "--port", "0")
                WindowProof.wait(lambda: (root / ".punt-labs/lux/hub.port").exists())
                display = start("luxd-display", "--socket", str(display_path))
                WindowProof.wait(lambda: display_path.exists())
                program = root / "program.py"
                program.write_text(PROGRAM)
                command = shlex.join([sys.executable, "-u", str(program), str(root)])
                rows = [
                    [str(i), f"row-{i:04d}", "ready", str(i * 7), "terminal-neighbor", str(i % 17)]
                    for i in range(1000)
                ]
                payload = {
                    "title": "Keyboard / table / finite flood",
                    "elements": [
                        {
                            "kind": "text",
                            "id": "label",
                            "content": "OS keyboard path with 1,000-row table below",
                        },
                        {
                            "kind": "terminal",
                            "id": "term",
                            "session": "keyboard-table",
                            "command": command,
                            "height": 250,
                        },
                        {"kind": "text", "id": "tablelabel", "content": "TABLE 1000 ROWS"},
                        {
                            "kind": "table",
                            "id": "heavy",
                            "columns": ["id", "name", "state", "value", "context", "rank"],
                            "rows": rows,
                        },
                    ],
                }
                scene = root / "scene.json"
                scene.write_text(json.dumps(payload))
                cli("scene", "show", "keyboard-table", "--from", str(scene), "--json")
                WindowProof.wait(lambda: "connected_active" in cli("display", "link", "--json"))
                WindowProof.wait(lambda: pty.exists() and bool(WindowProof.listing(pty)))
                capture.raise_window(display.pid)
                capture.display_pids = lambda: [display.pid]
                setup = capture.capture(Path("/tmp/lux-keyboard-table-setup.png"))
                setup_text = subprocess.run(
                    ["tesseract", str(setup), "stdout"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout
                print("SETUP OCR", setup_text, file=sys.stderr)
                assert "KEYBOARD_READY" in setup_text, setup_text
                assert not WindowProof.listing(pty)[0]["ended"]
                print(
                    "GEOMETRY",
                    cli("scene", "inspect", "keyboard-table", "--geometry", "--json"),
                    file=sys.stderr,
                )
                win = capture.find_window([display.pid])
                point = (win.bounds.x + 150, win.bounds.y + 150)
                assert q.CGWarpMouseCursorPosition(point) == 0
                time.sleep(0.1)
                for kind in (q.kCGEventMouseMoved, q.kCGEventLeftMouseDown, q.kCGEventLeftMouseUp):
                    event = q.CGEventCreateMouseEvent(None, kind, point, q.kCGMouseButtonLeft)
                    q.CGEventSetIntegerValueField(
                        event, q.kCGMouseEventWindowUnderMousePointer, win.number
                    )
                    q.CGEventSetIntegerValueField(
                        event,
                        q.kCGMouseEventWindowUnderMousePointerThatCanHandleThisEvent,
                        win.number,
                    )
                    q.CGEventPostToPid(display.pid, event)
                    time.sleep(0.075)
                clicked = subprocess.run(
                    [
                        "osascript",
                        "-e",
                        'tell application "System Events" to tell '
                        f"(first application process whose unix id is {display.pid}) "
                        f"to click at {{{int(point[0])},{int(point[1])}}}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                print("TARGETED CLICK", clicked.returncode, clicked.stderr, file=sys.stderr)
                assert clicked.returncode == 0
                time.sleep(0.15)
                try:
                    warm = measure(display, "warm")
                except TimeoutError:
                    failed = capture.capture(Path("/tmp/lux-keyboard-table-input-failed.png"))
                    text = subprocess.run(
                        ["tesseract", str(failed), "stdout"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=True,
                    ).stdout
                    print("INPUT FAILED OCR", text, file=sys.stderr)
                    raise
                quiet = [measure(display, f"q{i}") for i in range(5)]
                capture.display_pids = lambda: [display.pid]
                before = capture.capture(Path("/tmp/lux-keyboard-table-quiet.png"))
                text = subprocess.run(
                    ["tesseract", str(before), "stdout"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout
                assert "ACK:q4" in "".join(text.split()), text
                assert "TABLE1000ROWS" in "".join(text.split()), text
                info_quiet = json.loads(cli("display", "info", "--json"))
                measure(display, "burst")
                WindowProof.wait(lambda: (root / "started").exists())
                busy = []
                for i in range(5):
                    assert not (root / "done").exists(), "probe must overlap burst"
                    busy.append(measure(display, f"b{i}"))
                    assert not (root / "done").exists(), "probe must overlap burst"
                info_busy = json.loads(cli("display", "info", "--json"))
                WindowProof.wait(lambda: (root / "done").exists())
                after = capture.capture(Path("/tmp/lux-keyboard-table-burst.png"))
                text = subprocess.run(
                    ["tesseract", str(after), "stdout"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout
                assert "ACK:b4" in "".join(text.split()), text
                assert "TABLE1000ROWS" in "".join(text.split()), text
                report.update(
                    program_pid=WindowProof.listing(pty)[0]["pid"],
                    display_pid=display.pid,
                    table_rows=1000,
                    burst_payload_bytes=80 * 204 * 514,
                    warm_key_to_response_ms=round(warm, 3),
                    quiet=KeyboardProof.summary(quiet),
                    during_burst=KeyboardProof.summary(busy),
                    display_info_quiet=info_quiet,
                    display_info_during_burst=info_busy,
                    screenshots=[str(before), str(after)],
                    scope=(
                        "Quartz PID-targeted Enter down to program readline; "
                        "eventual pixels checked, first-pixel latency NOT measured"
                    ),
                )
                WindowProof.stop(display)
                client = WireClient(pty)
                try:
                    client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
                    assert isinstance(
                        client.request(KillRequest(2, "keyboard-table")), SuccessReply
                    )
                finally:
                    client.close()
            finally:
                for process in reversed(processes):
                    WindowProof.stop(process)
                owner = WindowProof.daemon_pid(pty)
                if owner is not None:
                    os.kill(owner, signal.SIGTERM)
                    WindowProof.wait(lambda: WindowProof.daemon_pid(pty) is None)
                q.CGWarpMouseCursorPosition(original_mouse)
                assert not pty.exists()
                for log in root.glob("*.log"):
                    print(log.name, log.read_text(errors="replace")[-600:], file=sys.stderr)
            report["cleanup"] = (
                "owned programs/Displays/Hub/daemon stopped; private instance removed"
            )
        Path("/tmp/lux-keyboard-table-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    KeyboardProof.main()
