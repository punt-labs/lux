"""End-to-end: a session's own process registers its menu entry and services a click.

The real ``lux mcp-serve`` binary runs as a subprocess against a real luxd, the
way Claude Code runs it. Nobody asks it to register anything: it puts its Beads
entry in the Hub's menu on connect, and when a click is routed to that entry it
does the work and pushes the board — on its own thread, with nothing polling and
no model in the loop.

This is the session-side counterpart of the vox Music Player acceptance scenario.
What a real display would add is the pixel hit-test that turns a click into an
invocation; the invocation routed here is the Hub's own leaf id, byte-identical
to what the display would send.

Driving the shipped process rather than the leg in-process is deliberate. The leg
has no stop — its life is its process's life — so an in-process leg would outlive
the test, keep reconnecting, and eventually find the developer's real Hub. A
subprocess ends when the test closes its stdin, which is also the behavior worth
proving.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

import anyio
import pytest
import uvicorn

from punt_lux.domain.hub.replicator_instance import hub_callback_router
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.luxd import build_app

pytestmark = pytest.mark.integration

# The first thing any MCP client sends; the reply proves the process is serving.
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "session-leg-test", "version": "0"},
    },
}


@contextmanager
def _running_luxd() -> Generator[int]:
    """Serve the assembled app on an ephemeral loopback port; yield the port."""
    config = uvicorn.Config(build_app(), host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: anyio.run(server.serve), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not server.started:
            raise RuntimeError("luxd did not start within 10s")
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@contextmanager
def _session_process(port: int, home: Path) -> Generator[subprocess.Popen[str]]:
    """Run the shipped ``lux mcp-serve`` against ``port``, and end it on exit.

    The process finds luxd through the port file under its home directory, so a
    temporary home points it at this test's Hub and nothing else.
    """
    (home / ".punt-labs" / "lux").mkdir(parents=True)
    (home / ".punt-labs" / "lux" / "hub.port").write_text(str(port))
    proc = subprocess.Popen(
        [sys.executable, "-m", "punt_lux", "mcp-serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(_INITIALIZE) + "\n")
        proc.stdin.flush()
        proc.stdout.readline()  # serving; its leg is connecting behind this
        yield proc
    finally:
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise


def _get(port: int, path: str) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return str(resp.read().decode())


def _until(predicate: Callable[[], bool], *, timeout: float = 15.0) -> None:
    """Spin until the predicate holds — the session's work happens off-process."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not reached within timeout")


def _leaf_id(port: int, label: str) -> str:
    """Return the menu leaf a display would carry back from a click on ``label``."""
    menus = json.loads(_get(port, "/menus"))["menus"]
    for menu in menus:
        for item in menu["items"]:
            if item["label"] == label:
                return str(item["id"])
    raise AssertionError(f"no {label!r} leaf in {menus}")


def _beads_scenes(port: int) -> list[str]:
    scenes = json.loads(_get(port, "/scenes"))["scenes"]
    return [s["scene_id"] for s in scenes if s["scene_id"].startswith("beads-")]


def test_a_session_process_registers_its_entry_and_services_a_click(
    tmp_path: Path,
) -> None:
    with _running_luxd() as port, _session_process(port, tmp_path / "home") as proc:
        # The entry appears under this session's own submenu, unasked.
        _until(lambda: "Beads" in _get(port, "/menus"))
        leaf = _leaf_id(port, "Beads")

        # Routing the Hub's own leaf id is what a display click does once the
        # pixel hit-test has run; everything after this point is production.
        assert hub_callback_router.route(CallbackInvocation.from_menu_id(leaf)) == (
            "routed"
        )

        # The session did the work and pushed a board. Which board it is depends
        # on whether bd is installed here — issues or the named failure message —
        # so this asserts the scene arrived, not what it says.
        _until(lambda: _beads_scenes(port) != [])
        assert len(_beads_scenes(port)) == 1

    # And the process left with its session, taking its menu entry's owner away.
    assert proc.returncode == 0
