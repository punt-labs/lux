"""An externally terminated proof reaps its detached owner and terminal child."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

pytestmark = pytest.mark.integration

PROOF = """
import json, pathlib, shlex, subprocess, sys, tempfile, time
from spikes.terminal.proof_signals import ProofSignals
from punt_lux.wire.stream.attach import AttachRequest
from punt_lux.wire.stream.control import WIRE_VERSION
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.replies import SuccessReply
from punt_lux.wire.stream.session_requests import ListRequest
from punt_lux.terminal.snapshot import snapshot_version
from tests.pty.wire_client import WireClient

with tempfile.TemporaryDirectory(prefix="proof-", dir="/tmp") as root:
    path = pathlib.Path(root) / "pty.sock"
    processes = []
    def cleanup():
        for owner in processes:
            owner.terminate()
            assert owner.wait(timeout=5) == 0
        assert not path.exists()
    with ProofSignals(cleanup):
        owner = subprocess.Popen([
            sys.executable, "-m", "punt_lux.pty", "--no-menu", "--socket", str(path)
        ])
        processes.append(owner)
        end = time.monotonic() + 5
        while not path.exists() and time.monotonic() < end:
            assert owner.poll() is None
            time.sleep(0.01)
        client = WireClient(path)
        try:
            assert isinstance(client.request(HelloRequest(
                1, WIRE_VERSION, snapshot_version()
            )), SuccessReply)
            command = shlex.join([
                sys.executable, "-c", "import time; time.sleep(60)"
            ])
            assert isinstance(client.request(AttachRequest(
                2, "proof", command
            )), SuccessReply)
            listing = client.request(ListRequest(3))
            assert isinstance(listing, SuccessReply)
            pid = listing.result["sessions"][0]["pid"]
        finally:
            client.close()
        pathlib.Path(sys.argv[1]).write_text(json.dumps([owner.pid, pid]))
        while True:
            time.sleep(1)
"""


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_external_signal_reaps_detached_daemon_and_session(
    tmp_path: Path, sig: signal.Signals
) -> None:
    ready = tmp_path / "ready.json"
    process = subprocess.Popen(
        [sys.executable, "-c", PROOF, str(ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pids: list[int] = []
    try:
        deadline = time.monotonic() + 10
        while (
            not ready.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert ready.exists(), "proof never created its session"
        pids = json.loads(ready.read_text())
        assert os.getsid(pids[0]) == pids[0]
        assert os.getsid(pids[1]) == pids[1]
        process.send_signal(sig)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 128 + sig, (stdout, stderr)
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
        for pid in pids:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
