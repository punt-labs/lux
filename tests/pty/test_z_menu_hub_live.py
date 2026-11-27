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
from punt_lux.terminal.snapshot import snapshot_version
from punt_lux.wire.model.session_callback import CallbackInvocation
from punt_lux.wire.stream.control import WIRE_VERSION
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.replies import SuccessReply
from punt_lux.wire.stream.session_requests import ListRequest
from tests.beads.test_beads_e2e import _get, _leaf_id, _running_luxd, _until
from tests.pty.wire_client import WireClient

pytestmark = pytest.mark.integration


def _local_ids(port: int) -> list[str]:
    scenes = json.loads(_get(port, "/scenes"))["scenes"]
    return [scene["local_id"] for scene in scenes]


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
            [sys.executable, "-m", "punt_lux.pty", "--socket", str(path)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _until(lambda: "New terminal" in _get(port, "/menus"), timeout=8)
            client = WireClient(path)
            try:
                client.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
                listing = client.request(ListRequest(2))
                assert isinstance(listing, SuccessReply)
                assert listing.result["sessions"] == []
            finally:
                client.close()
            assert json.loads(_get(port, "/scenes"))["scenes"] == []
            leaf = _leaf_id(port, "New terminal")
            assert (
                hub_callback_router.route(CallbackInvocation.from_menu_id(leaf))
                == "routed"
            )
            _until(lambda: len(_local_ids(port)) == 1, timeout=8)
            assert _local_ids(port)[0].startswith("terminal-")
            assert (
                hub_callback_router.route(CallbackInvocation.from_menu_id(leaf))
                == "routed"
            )
            _until(lambda: len(set(_local_ids(port))) == 2, timeout=8)
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
