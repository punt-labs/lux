"""Mac isolated-window proof. Run with python -m spikes.terminal.check_daemon_window.

LUX_CAPTURE_SCRIPT must point to the reviewed macOS screenshot helper (Lux main
scripts/screenshot_macos.py). Only the test Display PID is passed to it. Normal
Lux services are neither queried nor altered. Wrap execution in timeout 110.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
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

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.protocol.pty.session_requests import KillRequest, ListRequest
from punt_lux.ptyd.snapshot import snapshot_version
from tests.ptyd.wire_client import WireClient
from spikes.terminal.proof_signals import ProofSignals

ROOT = Path(__file__).resolve().parents[2]
capture_script = Path(os.environ["LUX_CAPTURE_SCRIPT"]).resolve()
spec = importlib.util.spec_from_file_location("shot", capture_script)
shot = importlib.util.module_from_spec(spec)
sys.modules["shot"] = shot
spec.loader.exec_module(shot)


def stop(p):
    if p.poll() is not None:
        return
    p.terminate()
    end = time.monotonic() + 4
    while p.poll() is None and time.monotonic() < end:
        time.sleep(0.02)
    if p.poll() is None:
        p.kill()
        p.wait(timeout=3)


def daemon_pid(path):
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=4, check=True
    )
    candidates = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if (
            len(fields) == 2
            and "-m punt_lux.ptyd --socket " in fields[1]
            and fields[1].endswith(str(path))
        ):
            candidates.append(int(fields[0]))
    assert len(candidates) <= 1, candidates
    return candidates[0] if candidates else None


def listing(path):
    c = WireClient(path)
    try:
        assert isinstance(
            c.request(HelloRequest(1, WIRE_VERSION, snapshot_version())), SuccessReply
        )
        r = c.request(ListRequest(2))
        assert isinstance(r, SuccessReply)
        return r.result["sessions"]
    finally:
        c.close()


def waitfor(condition, seconds=12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if condition():
                return
        except (shot.ScreenshotError, OSError):
            pass
        time.sleep(0.05)
    raise AssertionError("bounded wait failed")


with (
    tempfile.TemporaryDirectory(prefix="lxw5-", dir="/tmp") as directory,
    ExitStack() as logs,
):
    run = Path(directory)
    pty = run / "pty" / "p.sock"
    display_path = run / "display.sock"
    env = dict(
        os.environ,
        HOME=str(run),
        LUX_SOCKET=str(display_path),
        LUX_PTY_SOCKET=str(pty),
        LUX_LOG_LEVEL="INFO",
    )
    processes = []

    def start(binary, *args):
        log = logs.enter_context(open(run / (binary + str(len(processes)) + ".log"), "wb"))
        p = subprocess.Popen(
            [str(ROOT / ".venv/bin" / binary), *args], cwd=run, env=env, stdout=log, stderr=log
        )
        processes.append(p)
        return p

    def cli(*args):
        r = subprocess.run(
            [str(ROOT / ".venv/bin/lux"), *args],
            cwd=run,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r.returncode == 0, (r.stdout, r.stderr)
        return r.stdout

    def cleanup():
        for p in reversed(processes):
            stop(p)
        pid = daemon_pid(pty)
        if pid is not None:
            os.kill(pid, signal.SIGTERM)
            end = time.monotonic() + 4
            while daemon_pid(pty) is not None and time.monotonic() < end:
                time.sleep(0.05)
            if daemon_pid(pty) == pid:
                os.kill(pid, signal.SIGKILL)
        for log in run.glob("*.log"):
            text = log.read_text(errors="replace")
            print(log.name, "tail", text[-1300:], flush=True)
        assert daemon_pid(pty) is None
        print("All isolated processes stopped; temp instance removed on exit", flush=True)

    with ProofSignals(cleanup):
        hub = start("luxd-hub", "--port", "0")
        waitfor(lambda: (run / ".punt-labs/lux/hub.port").exists())
        first = start("luxd-display", "--socket", str(display_path))
        waitfor(lambda: display_path.exists())
        waitfor(lambda: pty.exists())
        assert listing(pty) == [], "launcher availability must not start a shell"
        waitfor(lambda: "Terminal" in cli("menu", "ls", "--json"))
        code = (
            "import sys,time; print('COLD START: owner survives Display crash',flush=True); "
            "sys.stdin.readline(); chunk='x'*79+'\\n'; "
            "[(sys.stdout.write(chunk*204),sys.stdout.flush(),time.sleep(.010)) "
            "for _ in range(322)]; "
            "print('BURST DONE: owner survives Display crash',flush=True); sys.stdin.readline()"
        )
        command = shlex.join([sys.executable, "-u", "-c", code])
        payload = {
            "title": "Stage 5 isolated proof",
            "elements": [
                {
                    "kind": "text",
                    "id": "note",
                    "content": "Lazy daemon / independent shell lifetime",
                },
                {
                    "kind": "terminal",
                    "id": "terminal",
                    "session": "window-proof",
                    "command": command,
                    "height": 350,
                },
            ],
        }
        scene = run / "scene.json"
        scene.write_text(json.dumps(payload))
        cli("scene", "show", "stage5", "--from", str(scene), "--json")
        waitfor(lambda: pty.exists() and bool(listing(pty)))
        before = listing(pty)
        dpid = daemon_pid(pty)
        assert dpid is not None
        waitfor(lambda: bool(shot.find_window([first.pid])))
        time.sleep(1)
        shot.display_pids = lambda: [first.pid]
        cold = shot.capture(Path("/tmp/lux-stage5-cold.png"))
        text = subprocess.run(
            ["tesseract", str(cold), "stdout"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        assert "owner survives Display crash" in text, text
        print("cold", json.dumps(before), "daemon", dpid, "image", cold, "OCR verified", flush=True)
        port = int((run / ".punt-labs/lux/hub.port").read_text())
        http = http.client.HTTPConnection("127.0.0.1", port, timeout=3)

        def pings():
            samples = []
            for _ in range(20):
                t = time.monotonic()
                http.request("GET", "/display/ping")
                response = http.getresponse()
                body = response.read()
                assert response.status == 200, (response.status, body)
                samples.append((time.monotonic() - t) * 1000)
                time.sleep(0.015)
            return {
                "median_ms": round(statistics.median(samples), 3),
                "p95_ms": round(sorted(samples)[18], 3),
                "max_ms": round(max(samples), 3),
                "samples": len(samples),
            }

        quiet = pings()
        c = WireClient(pty)
        try:
            c.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
            attached = c.request(AttachRequest(2, "window-proof", command))
            assert isinstance(attached, SuccessReply)
            channel, checkpoint = c.snapshot(dict(attached.result))
            c.send(Frame(channel, FrameKind.DATA, b"burst\n"))
        finally:
            c.close()
        busy = pings()
        http.close()
        assert listing(pty)[0]["position"] < 80 * 204 * 322, "probes must all overlap the burst"
        waitfor(lambda: listing(pty)[0]["position"] > 80 * 204 * 322 + 50)
        shot.display_pids = lambda: [first.pid]
        burst = shot.capture(Path("/tmp/lux-stage5-burst.png"))
        text = subprocess.run(
            ["tesseract", str(burst), "stdout"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        assert "BURST DONE" in text, text
        before = listing(pty)
        report = {
            "payload_bytes": 80 * 204 * 322,
            "quiet_hub_display_ping": quiet,
            "finite_burst_hub_display_ping": busy,
            "scope": "actual GUI ping via Hub REST; not keyboard-to-pixel latency",
        }
        Path("/tmp/lux-window-ping.json").write_text(json.dumps(report, indent=2))
        print("GUI PING MEASUREMENTS", json.dumps(report), flush=True)
        first.kill()
        first.wait(timeout=4)
        time.sleep(0.15)
        absent = listing(pty)
        assert absent[0]["pid"] == before[0]["pid"] and not absent[0]["ended"]
        second = start("luxd-display", "--socket", str(display_path))
        waitfor(lambda: bool(shot.find_window([second.pid])))
        waitfor(lambda: "connected_active" in cli("display", "link", "--json"), seconds=22)
        time.sleep(1)
        after = listing(pty)
        assert after[0]["pid"] == before[0]["pid"] and not after[0]["ended"]
        assert daemon_pid(pty) == dpid
        shot.display_pids = lambda: [second.pid]
        resumed = shot.capture(Path("/tmp/lux-stage5-resumed.png"))
        text = subprocess.run(
            ["tesseract", str(resumed), "stdout"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        assert "owner survives Display crash" in text, text
        print("resumed", json.dumps(after), "image", resumed, "OCR verified", flush=True)
        stop(second)
        c = WireClient(pty)
        try:
            c.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
            assert isinstance(c.request(KillRequest(2, "window-proof")), SuccessReply)
        finally:
            c.close()
        print("ACTUAL-WINDOW COLD START / SIGKILL / RESTART PASSED", flush=True)
