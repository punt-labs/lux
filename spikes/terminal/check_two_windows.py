"""Two isolated real Displays share one PTY owner; one can crash independently.

Run with LUX_CAPTURE_SCRIPT=../lux/scripts/screenshot_macos.py timeout 120
.venv/bin/python -m spikes.terminal.check_two_windows. Capture tool is read-only;
only owned Display PIDs are selected. Requires macOS capture permission/ffmpeg/OCR.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.protocol.pty.session_requests import KillRequest, ListRequest
from punt_lux.ptyd.snapshot import snapshot_version
from tests.ptyd.wire_client import WireClient

ROOT = Path(__file__).resolve().parents[2]


class WindowProof:
    @staticmethod
    def wait(condition: Callable[[], bool]) -> None:
        end = time.monotonic() + 18
        while time.monotonic() < end:
            try:
                if condition():
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise TimeoutError("isolated window check deadline exceeded")

    @staticmethod
    def stop(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        end = time.monotonic() + 4
        while process.poll() is None and time.monotonic() < end:
            time.sleep(0.02)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)

    @staticmethod
    def daemon_pid(path: Path) -> int | None:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=4,
            check=True,
        )
        matches = []
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if (
                len(parts) == 2
                and "-m punt_lux.ptyd --socket " in parts[1]
                and parts[1].endswith(str(path))
            ):
                matches.append(int(parts[0]))
        assert len(matches) <= 1, matches
        return matches[0] if matches else None

    @staticmethod
    def listing(path: Path) -> list[dict[str, object]]:
        client = WireClient(path)
        try:
            client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
            reply = client.request(ListRequest(2))
            assert isinstance(reply, SuccessReply)
            return cast("list[dict[str, object]]", reply.result["sessions"])
        finally:
            client.close()

    @staticmethod
    def main() -> None:
        spec = importlib.util.spec_from_file_location(
            "capture", Path(os.environ["LUX_CAPTURE_SCRIPT"]).resolve()
        )
        assert spec is not None and spec.loader is not None
        capture: Any = importlib.util.module_from_spec(spec)
        sys.modules["capture"] = capture
        spec.loader.exec_module(capture)
        processes: list[subprocess.Popen[bytes]] = []
        evidence: dict[str, object] = {}
        with (
            tempfile.TemporaryDirectory(prefix="lxmv-", dir="/tmp") as directory,
            ExitStack() as logs,
        ):
            root = Path(directory)
            pty = root / "pty" / "p.sock"
            environments: list[dict[str, str]] = []
            for index in (1, 2):
                home = root / f"home{index}"
                home.mkdir(mode=0o700)
                environments.append(
                    dict(
                        os.environ,
                        HOME=str(home),
                        LUX_SOCKET=str(home / "d.sock"),
                        LUX_PTY_SOCKET=str(pty),
                        LUX_LOG_LEVEL="INFO",
                    )
                )

            def start(env: dict[str, str], binary: str, *args: str) -> subprocess.Popen[bytes]:
                log = logs.enter_context(open(root / f"{binary}-{len(processes)}.log", "wb"))
                process = subprocess.Popen(
                    [str(ROOT / ".venv/bin" / binary), *args],
                    env=env,
                    cwd=env["HOME"],
                    stdout=log,
                    stderr=log,
                )
                processes.append(process)
                return process

            def cli(env: dict[str, str], *args: str) -> str:
                result = subprocess.run(
                    [str(ROOT / ".venv/bin/lux"), *args],
                    env=env,
                    cwd=env["HOME"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                assert result.returncode == 0, (result.stdout, result.stderr)
                return result.stdout

            def show(env: dict[str, str]) -> None:
                cli(env, "scene", "show", "shared-proof", json.dumps(payload), "--json")
                WindowProof.wait(
                    lambda: "connected_active" in cli(env, "display", "link", "--json")
                )

            def screenshot(process: subprocess.Popen[bytes], name: str, marker: str) -> str:
                assert process.poll() is None
                capture.display_pids = lambda: [process.pid]
                path = capture.capture(Path("/tmp") / name)
                text = subprocess.run(
                    ["tesseract", str(path), "stdout"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout
                assert "".join(marker.split()) in "".join(text.split()), text
                return str(path)

            command = shlex.join(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import os,sys; print('SHARED PID: '+str(os.getpid()),flush=True); "
                    "[print('UPDATE:'+line.strip(),flush=True) for line in sys.stdin]",
                ]
            )
            payload = {
                "title": "Two-viewer independent lifetime",
                "elements": [
                    {
                        "kind": "text",
                        "id": "label",
                        "content": "One owner, two independent Display replicas",
                    },
                    {
                        "kind": "terminal",
                        "id": "term",
                        "session": "shared-windows",
                        "command": command,
                        "height": 350,
                    },
                ],
            }
            try:
                displays = []
                for env in environments:
                    start(env, "luxd-hub", "--port", "0")
                    WindowProof.wait(
                        lambda env=env: (Path(env["HOME"]) / ".punt-labs/lux/hub.port").exists()
                    )
                    display = start(env, "luxd-display", "--socket", env["LUX_SOCKET"])
                    displays.append(display)
                    WindowProof.wait(lambda env=env: Path(env["LUX_SOCKET"]).exists())
                    show(env)
                    WindowProof.wait(lambda: pty.exists() and bool(WindowProof.listing(pty)))
                sessions = WindowProof.listing(pty)
                assert len(sessions) == 1
                pid = sessions[0]["pid"]
                owner = WindowProof.daemon_pid(pty)
                assert owner is not None
                marker = f"SHARED PID: {pid}"
                time.sleep(0.5)
                evidence["both_windows"] = [
                    screenshot(display, f"lux-two-window-{index}.png", marker)
                    for index, display in enumerate(displays, 1)
                ]
                evidence.update(
                    program_pid=pid, owner_pid=owner, display_pids=[p.pid for p in displays]
                )
                displays[0].kill()
                displays[0].wait(timeout=4)
                client = WireClient(pty)
                try:
                    client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
                    reply = client.request(AttachRequest(2, "shared-windows", command))
                    assert isinstance(reply, SuccessReply)
                    channel, _checkpoint = client.snapshot(dict(reply.result))
                    client.send(Frame(channel, FrameKind.DATA, b"survivor\n"))
                finally:
                    client.close()
                time.sleep(0.5)
                evidence["survivor_window"] = screenshot(
                    displays[1], "lux-two-window-survivor.png", "UPDATE:survivor"
                )
                replacement = start(
                    environments[0], "luxd-display", "--socket", environments[0]["LUX_SOCKET"]
                )
                WindowProof.wait(
                    lambda: "connected_active" in cli(environments[0], "display", "link", "--json")
                )
                time.sleep(0.5)
                evidence["rejoined_window"] = screenshot(
                    replacement, "lux-two-window-rejoined.png", "UPDATE:survivor"
                )
                after = WindowProof.listing(pty)
                assert after[0]["pid"] == pid and not after[0]["ended"]
                assert WindowProof.daemon_pid(pty) == owner
                evidence["rejoined_display_pid"] = replacement.pid
                for display in [*displays, replacement]:
                    WindowProof.stop(display)
                client = WireClient(pty)
                try:
                    client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
                    assert isinstance(
                        client.request(KillRequest(2, "shared-windows")), SuccessReply
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
                assert not pty.exists()
                for log in root.glob("*.log"):
                    print(log.name, log.read_text(errors="replace")[-600:], file=sys.stderr)
            evidence["cleanup"] = (
                "owned Displays/Hubs/daemon/program stopped; private instance removed"
            )
        Path("/tmp/lux-two-window-result.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    WindowProof.main()
