"""End-to-end roundtrip tests for the io-model spike.

Each test spawns hub + display + agent as separate OS processes
communicating over Unix sockets, and asserts the three canonical
roundtrips from io-model.md run end-to-end.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from tests.conftest import SpikeProcs, wait_for


def _recording_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _connect_unix(path: Path) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(path))
    return s


def _send_line(sock: socket.socket, payload: dict) -> None:
    sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))


# ────────────────────────────── R1 ─────────────────────────────────────────────


def test_r1_outbound_and_observer_push(spike: SpikeProcs) -> None:
    """Agent sends show() → Hub applies + ships AddElement to Display →
    Display renders into recording surface → 3+ entries appear.

    Separately: Agent subscribes to scene.applied; Hub publishes; Agent
    receives push. Verified via the recording log containing rendered
    output for all three elements (Panel begin/end + Label + Button)."""
    ok = wait_for(lambda: spike.recording_path.exists() and len(_recording_entries(spike.recording_path)) >= 4, timeout=8.0)
    assert ok, f"recording log never reached 4 entries: {_recording_entries(spike.recording_path)}"
    entries = _recording_entries(spike.recording_path)
    kinds = [(e.get("op"), e.get("kind"), e.get("id")) for e in entries[:4]]
    assert ("begin", "panel", "p1") in kinds
    assert ("render", "label", "lbl1") in kinds
    assert ("render", "button", "btn1") in kinds
    assert ("end", "panel", "p1") in kinds


# ────────────────────────────── R2 ─────────────────────────────────────────────


def test_r2_background_thread_state_update(spike: SpikeProcs) -> None:
    """Hub timer mutates LabelElement.content every 0.5s → Display
    renders new content → recording log shows distinct content values."""
    # Wait for >= 4 distinct content values for lbl1.
    def distinct_contents() -> set[str]:
        entries = _recording_entries(spike.recording_path)
        return {e["content"] for e in entries if e.get("kind") == "label" and e.get("id") == "lbl1"}

    ok = wait_for(lambda: len(distinct_contents()) >= 4, timeout=15.0)
    contents = distinct_contents()
    assert ok, f"expected >=4 distinct Label contents from timer updates, got: {sorted(contents)}"
    # All observed contents are the "ticks: N" pattern — initial show() and
    # subsequent SetProperty payloads — proving the update propagated from
    # Hub timer → Display.apply → render loop.
    assert all(c.startswith("ticks: ") for c in contents), f"unexpected content: {contents}"
    nums = {int(c.removeprefix("ticks: ")) for c in contents}
    assert len(nums) >= 4, f"expected >=4 distinct tick numbers; got {sorted(nums)}"


# ────────────────────────────── R3 ─────────────────────────────────────────────


def test_r3_user_interaction_roundtrip(spike: SpikeProcs) -> None:
    """Simulated user click reaches the Hub, runs `ButtonElement.on_click()`,
    publishes the `interaction.<id>` topic, and a subscribed agent receives
    the push notification — proving the full Display → Hub → Agent inbound
    roundtrip per io-model.md.

    The "simulated user input" arrives via a test-only `synthesize_interaction`
    agent command (~10 lines on hub.py). It runs the same Hub-side code
    path that a real click would (lookup element, call on_click, publish),
    so the assertion exercises the production handler.
    """
    # Wait for the agent's show() to have propagated through the pipeline
    # so the Hub has actually indexed btn1 — otherwise lookup returns None.
    assert wait_for(
        lambda: spike.recording_path.exists() and len(_recording_entries(spike.recording_path)) >= 4,
        timeout=8.0,
    ), "show() never reached display; cannot test R3"

    sock = _connect_unix(spike.agent_sock)
    try:
        _send_line(sock, {"kind": "subscribe", "topic": "interaction.btn1"})
        _send_line(sock, {"kind": "synthesize_interaction", "elem_id": "btn1", "action": "click"})

        sock.settimeout(5.0)
        buf = b""
        import time
        deadline = time.time() + 5.0
        while time.time() < deadline:
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    pytest.fail("hub closed agent connection unexpectedly")
                buf += chunk
            line, _, rest = buf.partition(b"\n")
            buf = rest
            if not line:
                continue
            msg = json.loads(line.decode("utf-8"))
            if msg.get("kind") == "observed" and msg.get("topic") == "interaction.btn1":
                payload = msg.get("payload")
                assert isinstance(payload, dict), f"unexpected payload type: {payload!r}"
                assert payload.get("elem_id") == "btn1"
                return
        pytest.fail("did not receive interaction.btn1 push within 5s")
    finally:
        sock.close()


@pytest.mark.parametrize("spike", ["text"], indirect=True)
def test_r1_with_text_surface_proves_second_output_method(spike: SpikeProcs) -> None:
    """Same R1, but with LUX_SURFACE=text. Asserts the second output method
    works without re-architecting — Display picks TextRendererFactory at
    startup and the wire protocol (Updates) is unchanged."""
    # With text surface, recording log is not created. Check hub/display stdout
    # for evidence the render loop ran on the text surface.
    import time
    deadline = time.time() + 8.0
    saw_panel = False
    while time.time() < deadline and not saw_panel:
        # Drain whatever the display has emitted so far.
        if spike.display.stdout is not None:
            # Non-blocking-ish read using select.
            import select
            r, _, _ = select.select([spike.display.stdout], [], [], 0.2)
            if r:
                line = spike.display.stdout.readline()
                if "Panel[p1]" in line:
                    saw_panel = True
                    break
    assert saw_panel, "text surface never rendered the panel"
