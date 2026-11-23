"""A supervised real PID/socket and HTTP facts traverse the full observer."""

from __future__ import annotations

import json
import select
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from punt_lux.kernel.hub_paths import HubPaths
from punt_lux.service import DISPLAY_SPEC
from punt_lux.service.display_paths import DisplayPaths
from punt_lux.service.display_restart import DisplayRestart

_DISPLAY = """
import socket, sys, setproctitle
path = sys.argv[1]
setproctitle.setproctitle(sys.argv[2])
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
    server.bind(path)
    server.listen(16)
    print('ready', flush=True)
    while True:
        connection, _ = server.accept()
        connection.close()
"""


@pytest.fixture
def socket_path() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="lux-r-") as directory:
        yield Path(directory) / "d.sock"


@pytest.mark.parametrize("refuse_first", [False, True])
def test_restart_reads_real_http_facts_and_kernel_socket_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    socket_path: Path,
    refuse_first: bool,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    process_name = f"lux-r-{uuid4().hex[:8]}"
    spec = replace(DISPLAY_SPEC, process_name=process_name)
    paths = DisplayPaths(socket_path)
    children: list[subprocess.Popen[str]] = []
    now = 0.0
    requests: list[str] = []

    def start_display() -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", _DISPLAY, str(paths.socket_path), process_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        children.append(child)
        assert child.stdout is not None
        assert select.select([child.stdout], [], [], 5)[0]
        assert child.stdout.readline().strip() == "ready"

    class Hub(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            payload = json.dumps(
                {
                    "pid": children[0].pid,
                    "hub_connection_id": "hub-start:1",
                    "uptime_seconds": now,
                    "protocol_version": "3",
                    "backend": "test",
                    "window_width": 800,
                    "window_height": 600,
                    "fps": 60,
                    "element_kinds": 25,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    def advance(seconds: float) -> None:
        nonlocal now
        now += seconds
        if refuse_first and now >= 1 and not thread.is_alive():
            hub.server_activate()
            thread.start()

    manager = MagicMock()
    manager.restart.side_effect = start_display
    with HTTPServer(("127.0.0.1", 0), Hub, bind_and_activate=False) as hub:
        hub.server_bind()
        hub_paths = HubPaths()
        hub_paths.dir.mkdir(parents=True)
        hub_paths.port_path.write_text(str(hub.server_port))
        thread = threading.Thread(target=hub.serve_forever, daemon=True)
        if not refuse_first:
            hub.server_activate()
            thread.start()
        try:
            with (
                patch(
                    "punt_lux.service._display_readiness.time.monotonic",
                    side_effect=lambda: now,
                ),
                patch(
                    "punt_lux.service._display_readiness.time.sleep",
                    side_effect=advance,
                ),
            ):
                result = DisplayRestart(spec=spec, manager=manager, paths=paths).run()
            assert f"pid {children[0].pid}" in result
            assert requests and set(requests) == {"/display"}
            assert now >= 3
        finally:
            if thread.is_alive():
                hub.shutdown()
                thread.join(timeout=5)
            for child in children:
                if child.poll() is None:
                    child.terminate()
                child.communicate(timeout=5)
