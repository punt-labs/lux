"""Spawn the three processes for an end-to-end roundtrip test.

Each test uses unique socket paths under tempfile.mkdtemp() so parallel
runs don't collide. The fixture tears down processes cleanly.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class SpikeProcs:
    hub: subprocess.Popen[str]
    display: subprocess.Popen[str]
    agent: subprocess.Popen[str]
    agent_sock: Path
    display_sock: Path
    recording_path: Path
    tmpdir: Path


def _spike_env(*, recording_path: Path, agent_sock: Path, display_sock: Path, surface: str, tick: float, hz: float) -> dict[str, str]:
    env = os.environ.copy()
    env["LUX_SPIKE_HUB_AGENT_SOCK"] = str(agent_sock)
    env["LUX_SPIKE_HUB_DISPLAY_SOCK"] = str(display_sock)
    env["LUX_SPIKE_RECORDING_PATH"] = str(recording_path)
    env["LUX_SURFACE"] = surface
    env["LUX_SPIKE_HUB_TICK_SECONDS"] = str(tick)
    env["LUX_SPIKE_DISPLAY_HZ"] = str(hz)
    env["LUX_SPIKE_DISPLAY_NO_STDIN"] = "1"  # tests use direct socket interaction, not stdin
    env["LUX_SPIKE_AGENT_RUN_SECONDS"] = "30"
    # Make python find the spike package even when running from the repo without install.
    src = Path(__file__).resolve().parent.parent / "src"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src}:{existing}" if existing else str(src)
    return env


@pytest.fixture
def spike(request: pytest.FixtureRequest) -> Iterator[SpikeProcs]:
    """Spawn hub, display, agent. Yield handles. Tear down on exit.

    Parametrize by surface via @pytest.mark.parametrize("surface", ["text", "recording"]).
    Defaults to "recording" (assertions read the JSONL log)."""
    surface = getattr(request, "param", "recording")
    tmp = Path(tempfile.mkdtemp(prefix="lux-spike-"))
    agent_sock = tmp / "agent.sock"
    display_sock = tmp / "display.sock"
    recording_path = tmp / "recording.jsonl"
    env = _spike_env(
        recording_path=recording_path,
        agent_sock=agent_sock,
        display_sock=display_sock,
        surface=surface,
        tick=0.5,   # fast timer for test snappiness
        hz=20.0,    # fast render loop
    )

    def spawn(module: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [sys.executable, "-m", f"lux_spike.{module}"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    hub = spawn("hub")
    # Give hub a beat to bind sockets before display + agent try to connect.
    time.sleep(0.5)
    display = spawn("display")
    time.sleep(0.5)
    agent = spawn("agent")

    procs = SpikeProcs(
        hub=hub,
        display=display,
        agent=agent,
        agent_sock=agent_sock,
        display_sock=display_sock,
        recording_path=recording_path,
        tmpdir=tmp,
    )

    yield procs

    # Teardown.
    for p in (procs.agent, procs.display, procs.hub):
        try:
            p.terminate()
        except ProcessLookupError:
            pass
    for p in (procs.agent, procs.display, procs.hub):
        try:
            p.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=2.0)
    # Best-effort cleanup; leaving tmpdir is OK on failures (helps debugging).
    if not request.session.testsfailed:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def wait_for(predicate, *, timeout: float = 5.0, interval: float = 0.05) -> bool:
    """Poll predicate() until it returns truthy or timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
