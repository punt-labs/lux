"""Isolated real Hub/Display/owner menu path, driving routing below pixel hit-test.

No actual supervisor install/enable. A test-only route exists only in the private
Hub process and calls the production callback router. Menu routing is not OS
mouse evidence. Run with LUX_CAPTURE_SCRIPT under timeout 120.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.terminal.snapshot import snapshot_version
from spikes.terminal.check_two_windows import WindowProof
from tests.ptyd.wire_client import WireClient

ROOT = Path(__file__).resolve().parents[2]
HUB_DRIVER = """
from punt_lux import luxd
from punt_lux.hub.replicator_instance import hub_callback_router
from punt_lux.hub.session_callback import CallbackInvocation
original=luxd.build_app
def build(**kwargs):
    app=original(**kwargs)
    def click(body:dict[str,str]):
        return {'outcome':hub_callback_router.route(CallbackInvocation.from_menu_id(body['id']))}
    app.add_api_route('/private-test-click',click,methods=['POST'])
    return app
luxd.build_app=build
luxd.main()
"""


class LauncherProof:
    @staticmethod
    def leaf(entries: list[dict[str, Any]]) -> str | None:
        for entry in entries:
            if entry.get("label") == "Terminal" and "id" in entry:
                return str(entry["id"])
            if isinstance(entry.get("items"), list):
                found = LauncherProof.leaf(entry["items"])
                if found is not None:
                    return found
        return None

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
        report: dict[str, object] = {}
        with (
            tempfile.TemporaryDirectory(prefix="lxlaunch-", dir="/tmp") as directory,
            ExitStack() as logs,
        ):
            root = Path(directory)
            pty = root / "pty/p.sock"
            display_path = root / "d.sock"
            env = dict(
                os.environ,
                HOME=str(root),
                LUX_SOCKET=str(display_path),
                LUX_PTY_SOCKET=str(pty),
                LUX_LOG_LEVEL="INFO",
            )
            env.pop("LUX_PTY_NO_MENU", None)

            def start(name: str, argv: list[str]) -> subprocess.Popen[bytes]:
                log = logs.enter_context(open(root / f"{name}-{len(processes)}.log", "wb"))
                process = subprocess.Popen(argv, cwd=root, env=env, stdout=log, stderr=log)
                processes.append(process)
                return process

            def hub() -> subprocess.Popen[bytes]:
                process = start("hub", [sys.executable, "-c", HUB_DRIVER, "--port", "0"])
                WindowProof.wait(lambda: (root / ".punt-labs/lux/hub.port").exists())
                return process

            def request(path: str, body: object = None) -> dict[str, Any]:
                port = int((root / ".punt-labs/lux/hub.port").read_text())
                data = None if body is None else json.dumps(body).encode()
                query = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(query, timeout=4) as response:
                    return json.loads(response.read())

            def marker(process: subprocess.Popen[bytes], name: str) -> str:
                capture.display_pids = lambda: [process.pid]
                image = capture.capture(Path("/tmp") / name)
                text = subprocess.run(
                    ["tesseract", str(image), "stdout"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout
                assert "MENU_LAUNCH_OK" in text, text
                return str(image)

            try:
                first_hub = hub()
                display = start(
                    "display", [str(ROOT / ".venv/bin/luxd-display"), "--socket", str(display_path)]
                )
                WindowProof.wait(lambda: display_path.exists())
                assert not pty.exists(), "Display must not enable a machine owner"
                owner = start(
                    "owner", [sys.executable, "-m", "punt_lux.ptyd", "--socket", str(pty)]
                )
                WindowProof.wait(lambda: pty.exists())
                WindowProof.wait(lambda: LauncherProof.leaf(request("/menus")["menus"]) is not None)
                assert WindowProof.listing(pty) == []
                assert request("/scenes")["scenes"] == []
                leaf = LauncherProof.leaf(request("/menus")["menus"])
                assert request("/private-test-click", {"id": leaf})["outcome"] == "routed"
                WindowProof.wait(lambda: bool(WindowProof.listing(pty)))
                sessions = WindowProof.listing(pty)
                pid = sessions[0]["pid"]
                assert sessions[0]["session"] == "luxd-pty-terminal"
                client = WireClient(pty)
                try:
                    client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
                    attached = client.request(AttachRequest(2, "luxd-pty-terminal"))
                    assert isinstance(attached, SuccessReply)
                    channel, _snapshot = client.snapshot(dict(attached.result))
                    client.send(Frame(channel, FrameKind.DATA, b"printf 'MENU_LAUNCH_OK\\n'\n"))
                finally:
                    client.close()
                time.sleep(0.3)
                first_image = marker(display, "lux-menu-launched.png")
                assert request("/private-test-click", {"id": leaf})["outcome"] == "routed"
                time.sleep(0.2)
                assert WindowProof.listing(pty)[0]["pid"] == pid
                WindowProof.stop(first_hub)
                # The full Hub entry removes its port file on ordinary shutdown.
                (root / ".punt-labs/lux/hub.port").unlink(missing_ok=True)
                second_hub = hub()
                WindowProof.wait(lambda: LauncherProof.leaf(request("/menus")["menus"]) is not None)
                WindowProof.wait(lambda: bool(request("/scenes")["scenes"]))
                time.sleep(0.5)
                restored_image = marker(display, "lux-menu-restored.png")
                assert WindowProof.listing(pty)[0]["pid"] == pid
                report.update(
                    program_pid=pid,
                    owner_pid=owner.pid,
                    display_pid=display.pid,
                    hub_pids=[first_hub.pid, second_hub.pid],
                    screenshots=[first_image, restored_image],
                    registration_before_shell=True,
                    repeated_launch_same_pid=True,
                    hub_restart_registration_and_scene_restore=True,
                    scope=("production router below OS hit-test; real window/OCR output"),
                )
            finally:
                for process in reversed(processes):
                    WindowProof.stop(process)
                assert not pty.exists()
                for log in root.glob("*.log"):
                    print(log.name, log.read_text(errors="replace")[-900:], file=sys.stderr)
            report["cleanup"] = (
                "owned Hub/Display/daemon/menu-helper/shell stopped; private instance removed"
            )
        Path("/tmp/lux-menu-launcher-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    LauncherProof.main()
