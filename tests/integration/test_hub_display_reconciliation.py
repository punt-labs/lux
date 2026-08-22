"""Hub/Display reconciliation harness — a luxd restart purges the dead Hub's ghost.

Mirrors ``tests/integration/test_subprocess_lifecycle.py``'s shape: spins up a
real Display subprocess and drives it over the real Unix socket, unstubbed.
Where that test proves the wire shape for one scene end to end, this one
proves DES-068's reconciliation: a Hub-identified connection dying without
killing the Display leaves a ghost scene behind, and a fresh Hub-identified
connection's empty manifest purges it — observed through the Display's own
introspection query, not a Hub-mediated read, since the point is what the
Display itself believes.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

import pytest

from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    ListScenesRequest,
    ListScenesResponse,
    TextElement,
    recv_message,
    send_message,
)


def _short_sock_path() -> tuple[str, Path]:
    """Return ``(tmpdir, sock_path)`` short enough for AF_UNIX (~104 chars)."""
    d = tempfile.mkdtemp(prefix="lux-")
    return d, Path(d) / "d.sock"


def _live_scene_ids(sock_path: Path) -> set[str]:
    """Query the Display's own scene list directly — no Hub in the loop.

    A plain, unidentified connection: ``list_scenes`` requires no identity,
    matching the introspection surface's own contract.
    """
    with DisplayLink(sock_path, auto_spawn=False, connect_timeout=5.0) as probe:
        sock = probe._sock  # test-only reach-through for a raw request/response
        assert sock is not None
        send_message(sock, ListScenesRequest())
        resp = recv_message(sock, timeout=5.0)
    assert isinstance(resp, ListScenesResponse)
    return {scene["scene_id"] for scene in resp.scenes}


def _wait_until(predicate: object, timeout: float = 5.0) -> bool:
    """Poll ``predicate()`` until it is true or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]  # test-only callable
            return True
        time.sleep(0.05)
    return False


@pytest.mark.e2e
@pytest.mark.gui
def test_a_restart_purges_the_dead_hubs_scene() -> None:
    """A fresh Hub identify with an empty manifest purges the dead Hub's ghost.

    The first connection identifies as ``kind="hub"``, pushes a scene, and
    disconnects (simulating ``luxd`` dying without killing the Display). The
    scene must still be showing afterward — nothing has reconciled yet. A
    second ``kind="hub"`` connection identifies and declares an empty
    manifest; the ghost must be gone. A scene pushed under the surviving
    connection afterward must render normally, proving reconciliation does
    not wedge subsequent ordinary traffic.
    """
    short_dir, sock_path = _short_sock_path()
    paths = DisplayPaths(sock_path)
    try:
        paths.ensure(timeout=10.0)
        assert paths.is_running()

        # The first "luxd": identifies as the Hub, pushes a scene, then dies
        # -- the Display process itself is untouched.
        with DisplayLink(
            sock_path, name="lux-mcp", kind="hub", auto_spawn=False, connect_timeout=5.0
        ) as first:
            ack = first.show(
                "ghost-scene", elements=[TextElement(id="t1", content="Ghost")]
            )
            assert ack is not None
            assert ack.scene_id == "ghost-scene"

        # Nothing has reconciled yet -- this is the bug's starting condition.
        assert _live_scene_ids(sock_path) == {"ghost-scene"}

        # The second "luxd": identifies as the Hub and declares it holds
        # nothing -- the ordinary post-restart manifest.
        second = DisplayLink(
            sock_path, name="lux-mcp", kind="hub", auto_spawn=False, connect_timeout=5.0
        )
        try:
            second.connect()
            second.send_manifest(())

            assert _wait_until(lambda: _live_scene_ids(sock_path) == set()), (
                "the ghost scene was never purged"
            )

            # Ordinary traffic still works under the surviving connection --
            # reconciliation does not wedge subsequent pushes.
            ack = second.show(
                "fresh-scene", elements=[TextElement(id="t2", content="Fresh")]
            )
            assert ack is not None
            assert ack.scene_id == "fresh-scene"
            assert _live_scene_ids(sock_path) == {"fresh-scene"}
        finally:
            second.close()
    finally:
        paths.reap(timeout=5.0)
        shutil.rmtree(short_dir, ignore_errors=True)
