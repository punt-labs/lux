"""Exercise Hub telemetry teardown against the daemon process."""

from __future__ import annotations

import os
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing
from typing import TYPE_CHECKING

import httpx
import pytest

from punt_lux.applets.claim import SessionClaim
from punt_lux.hub.hub_lifespan import HubLifespan
from punt_lux.kernel.hub_paths import HubPaths

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("existing_root", "claim_first"),
    [
        pytest.param(False, False, id="fresh"),
        pytest.param(True, True, id="legacy-claim-first"),
        pytest.param(True, False, id="legacy-hub-first"),
    ],
)
def test_hub_and_claim_share_a_private_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing_root: bool,
    claim_first: bool,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = HubPaths()
    previous_umask = os.umask(0o002)
    try:
        if existing_root:
            paths.dir.mkdir(parents=True)
            assert stat.S_IMODE(paths.dir.parent.stat().st_mode) == 0o775
            assert stat.S_IMODE(paths.dir.stat().st_mode) == 0o775
        if claim_first:
            assert SessionClaim.for_session("lux-beads", 4321).take()
        assert HubLifespan(paths).record_listening(8430) == os.getpid()
        assert paths.read_port() == 8430
        assert stat.S_IMODE(paths.dir.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(paths.dir.stat().st_mode) == 0o700
        assert SessionClaim.for_session("lux-beads", 4321).take()
        assert stat.S_IMODE((paths.dir / "sessions").stat().st_mode) == 0o700
    finally:
        os.umask(previous_umask)


@pytest.mark.parametrize("link_namespace", [False, True], ids=["root", "namespace"])
def test_hub_and_claim_use_an_owned_symlink_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, link_namespace: bool
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = HubPaths()
    link = paths.dir.parent if link_namespace else paths.dir
    link.parent.mkdir(mode=0o700, exist_ok=True)
    target = tmp_path / "relocated"
    target.mkdir()
    target.chmod(0o775)
    link.symlink_to(target, target_is_directory=True)
    root = target / "lux" if link_namespace else target

    assert HubLifespan(paths).record_listening(8430) == os.getpid()
    assert (root / "hub.port").read_text() == "8430"
    assert SessionClaim.for_session("lux-beads", 4321).take()
    assert (root / "sessions" / "lux-beads-4321.pid").is_file()
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


@pytest.mark.parametrize("link_namespace", [False, True], ids=["local", "relocated"])
def test_hub_and_claim_reject_a_symlink_in_a_writable_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, link_namespace: bool
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = HubPaths()
    namespace = paths.dir.parent
    if link_namespace:
        namespace = tmp_path / "relocated"
        paths.dir.parent.symlink_to(namespace, target_is_directory=True)
    namespace.mkdir()
    namespace.chmod(0o775)
    target = tmp_path / "unrelated"
    target.mkdir()
    target.chmod(0o755)
    paths.dir.symlink_to(target, target_is_directory=True)

    with pytest.raises(PermissionError, match="symlink in a writable directory"):
        HubLifespan(paths).record_listening(8430)
    with pytest.raises(PermissionError, match="symlink in a writable directory"):
        SessionClaim.for_session("lux-beads", 4321)

    assert stat.S_IMODE(namespace.stat().st_mode) == 0o775
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert not list(target.iterdir())


@pytest.mark.integration
def test_hub_flushes_render_metrics_on_sigterm(tmp_path: Path) -> None:
    state = tmp_path / ".punt-labs" / "lux"
    paths = HubPaths(state)
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PUNT_TELEMETRY": "on",
        "LUX_TELEMETRY": "on",
        "PUNT_TELEMETRY_EXPORTER": "sqlite",
    }
    command = [
        sys.executable,
        "-c",
        "from punt_lux.hub.luxd import main; main()",
        "--port",
        "0",
    ]
    with subprocess.Popen(command, cwd=tmp_path, env=env) as hub:
        try:
            deadline = time.monotonic() + 20
            port = paths.read_port()
            while port is None and hub.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
                port = paths.read_port()
            assert port is not None, f"Hub did not bind (exit={hub.poll()})"
            response = httpx.put(
                f"http://127.0.0.1:{port}/scenes/flush-test",
                json={"scene_id": "flush-test", "elements": []},
                headers={"X-Lux-Client-Kind": "cli", "X-Lux-Client-Name": "test"},
                timeout=5,
                trust_env=False,
            )
            assert response.status_code == 200
            assert response.json() == {"kind": "ok", "scene_id": "flush-test"}
            with closing(sqlite3.connect(state / "telemetry.db")) as db:
                before_shutdown = db.execute("SELECT count(*) FROM metric_points")
                assert before_shutdown.fetchone() == (0,)
            hub.terminate()
            assert hub.wait(timeout=20) == -signal.SIGTERM
        finally:
            if hub.poll() is None:
                hub.kill()
                hub.wait()

    with closing(sqlite3.connect(state / "telemetry.db")) as db:
        assert db.execute("SELECT name, count FROM metric_points").fetchall() == [
            ("lux.hub.operation_duration", 1)
        ]
