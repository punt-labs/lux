"""Real assembled Hub and daemon: launcher registers cold and services push clicks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

from punt_lux.hub.replicator_instance import hub_callback_router
from punt_lux.hub.session_callback import CallbackInvocation
from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.protocol.pty.session_requests import ListRequest
from punt_lux.terminal.snapshot import snapshot_version
from tests.applets.beads.test_beads_e2e import _get, _leaf_id, _running_luxd, _until
from tests.ptyd.wire_client import WireClient

pytestmark = pytest.mark.integration


def test_daemon_registers_menu_before_any_terminal_and_services_click() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="lxmenu-", dir="/tmp") as directory,
        _running_luxd() as port,
    ):
        home = Path(directory)
        state = home / ".punt-labs/lux"
        state.mkdir(parents=True)
        (state / "hub.port").write_text(str(port))
        path = home / "pty/p.sock"
        env = {**os.environ, "HOME": str(home)}
        env.pop("LUX_PTY_NO_MENU", None)
        process = subprocess.Popen(
            [sys.executable, "-m", "punt_lux.ptyd", "--socket", str(path)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _until(lambda: "Terminal" in _get(port, "/menus"), timeout=8)
            client = WireClient(path)
            try:
                client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
                listing = client.request(ListRequest(2))
                assert isinstance(listing, SuccessReply)
                assert listing.result["sessions"] == []
            finally:
                client.close()
            assert json.loads(_get(port, "/scenes"))["scenes"] == []
            leaf = _leaf_id(port, "Terminal")
            assert (
                hub_callback_router.route(CallbackInvocation.from_menu_id(leaf))
                == "routed"
            )
            _until(lambda: bool(json.loads(_get(port, "/scenes"))["scenes"]), timeout=5)
            scenes = json.loads(_get(port, "/scenes"))["scenes"]
            assert len(scenes) == 1
            assert scenes[0]["local_id"] == "terminal"
            assert (
                hub_callback_router.route(CallbackInvocation.from_menu_id(leaf))
                == "routed"
            )
            _until(lambda: len(json.loads(_get(port, "/scenes"))["scenes"]) == 1)
            assert process.poll() is None
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            assert process.stderr is not None
            errors = process.stderr.read().decode()
            process.stderr.close()
            assert process.returncode == 0, errors
            assert not path.exists()
