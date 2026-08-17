"""End-to-end: the shipped applet registers its entry, services a click, and leaves.

The real ``lux-beads`` binary runs as a subprocess against a real luxd, the way
the session-start hook runs it. Nobody asks it to register anything: it puts its
Beads entry in the Hub's menu on connect, and when a click is routed to that
entry it does the work and pushes the board — on its own loop, with nothing
polling and no model in the loop.

What a real display would add is the pixel hit-test that turns a click into an
invocation; the invocation routed here is the Hub's own leaf id, byte-identical
to what the display would send.

The lifetime is the other half. The applet watches the process it was told is its
session, so ending that process must end the applet — and it is checked here
against a real process rather than argued about, because an applet that outlives
its session is the failure the design exists to prevent.
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
from typing import Any

import anyio
import pytest
import uvicorn

from punt_lux.domain.hub.replicator_instance import hub_callback_router
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.luxd import build_app

pytestmark = pytest.mark.integration


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
            msg = "luxd did not start within 10s"
            raise RuntimeError(msg)
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@contextmanager
def _a_session() -> Generator[subprocess.Popen[bytes]]:
    """A stand-in for the Claude Code process an applet is bound to."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


@contextmanager
def _applet(
    port: int, home: Path, session_pid: int
) -> Generator[subprocess.Popen[str]]:
    """Run the shipped ``lux-beads`` against ``port``, bound to ``session_pid``.

    The applet finds luxd through the port file under its home directory, so a
    temporary home points it at this test's Hub and nothing else.
    """
    (home / ".punt-labs" / "lux").mkdir(parents=True)
    (home / ".punt-labs" / "lux" / "hub.port").write_text(str(port))
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "punt_lux.applets.beads",
            "--session-pid",
            str(session_pid),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def _get(port: int, path: str) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return str(resp.read().decode())


def _until(predicate: Callable[[], bool], *, timeout: float = 20.0) -> None:
    """Spin until the predicate holds — the applet's work happens off-process."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not reached within timeout")


def _leaf_id(port: int, label: str) -> str:
    """Return the menu leaf a display would carry back from a click on ``label``.

    The menu nests — a client sits under ``Clients`` — so the search descends
    the way the display's own decode does rather than reading one level.
    """
    menus = json.loads(_get(port, "/menus"))["menus"]
    found = _find_leaf(menus, label)
    if found is None:
        raise AssertionError(f"no {label!r} leaf in {menus}")
    return found


def _find_leaf(entries: list[dict[str, Any]], label: str) -> str | None:
    """Return the id of the first leaf reading *label*, or None if there is none.

    ``None`` is the documented absence — the caller turns it into the assertion
    that names what it was looking for and where it looked.
    """
    for entry in entries:
        if entry.get("label") == label and "id" in entry:
            return str(entry["id"])
        nested = entry.get("items")
        if isinstance(nested, list) and (found := _find_leaf(nested, label)):
            return found
    return None


def _beads_scenes(port: int) -> list[str]:
    scenes = json.loads(_get(port, "/scenes"))["scenes"]
    # local_id is the applet's own raw label (DES-086) — scene_id is composed
    # against the applet's connection, so filtering by it would never match.
    return [s["scene_id"] for s in scenes if s["local_id"].startswith("beads-")]


def test_the_applet_registers_its_entry_and_services_a_click(tmp_path: Path) -> None:
    with (
        _running_luxd() as port,
        _a_session() as session,
        _applet(port, tmp_path / "home", session.pid),
    ):
        # The entry appears under this session's own submenu, unasked.
        _until(lambda: "Beads" in _get(port, "/menus"))
        leaf = _leaf_id(port, "Beads")

        # Routing the Hub's own leaf id is what a display click does once the
        # pixel hit-test has run; everything after this point is production.
        assert hub_callback_router.route(CallbackInvocation.from_menu_id(leaf)) == (
            "routed"
        )

        # The applet did the work and pushed a board. Which board it is depends on
        # whether bd is installed here — issues or the named failure message — so
        # this asserts the scene arrived, not what it says.
        _until(lambda: _beads_scenes(port) != [])
        assert len(_beads_scenes(port)) == 1


def test_the_applet_leaves_when_its_session_does(tmp_path: Path) -> None:
    """The lifetime rule, against a real process rather than an argument."""
    with (
        _running_luxd() as port,
        _a_session() as session,
        _applet(port, tmp_path / "home", session.pid) as applet,
    ):
        _until(lambda: "Beads" in _get(port, "/menus"))

        session.kill()
        session.wait(timeout=10)

        # Bounded by the watch's poll interval, not by anything this test does.
        applet.wait(timeout=30)
        assert applet.returncode == 0
