"""End-to-end tests: full display server + client lifecycle.

These tests start the actual display server as a subprocess and exercise
the full protocol path.  They require a GPU-capable environment (ImGui).

Run with: uv run pytest -m e2e
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from punt_lux.client import LuxClient
from punt_lux.protocol import ButtonElement, InteractionMessage, TextElement


def _wait_for_socket(sock_path: Path, timeout: float = 10.0) -> None:
    """Poll until the socket file appears or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sock_path.exists():
            return
        time.sleep(0.1)
    msg = f"Display server did not create socket at {sock_path} within {timeout}s"
    raise TimeoutError(msg)


@pytest.mark.e2e
class TestWalkingSkeleton:
    """Walking skeleton: display subprocess + client round-trip + interaction."""

    def test_scene_ack_and_ping(self, tmp_path: Path) -> None:
        """Start display, connect, send scene with image+buttons, ping, shutdown."""
        sock_path = tmp_path / "display.sock"
        # Create a minimal PNG for the image element
        img_path = tmp_path / "test.png"
        img_path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
            b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
            b"\x00\x00\x00IEND\xaeB`\x82"
        )

        proc = subprocess.Popen(
            [sys.executable, "-m", "punt_lux", "display", "--socket", str(sock_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_socket(sock_path)

            with LuxClient(sock_path, auto_spawn=False, connect_timeout=5.0) as client:
                assert client.is_connected
                assert client.ready_message is not None

                # Send scene with image + 2 buttons
                from punt_lux.protocol import ImageElement

                ack = client.show(
                    "e2e-scene-1",
                    elements=[
                        ImageElement(
                            id="img1",
                            path=str(img_path),
                            alt="Test image",
                            width=100,
                            height=100,
                        ),
                        ButtonElement(id="btn-ok", label="OK", action="ok"),
                        ButtonElement(id="btn-cancel", label="Cancel", action="cancel"),
                    ],
                    title="E2E Test",
                )
                assert ack is not None
                assert ack.scene_id == "e2e-scene-1"

                # Verify bidirectional communication with ping
                pong = client.ping()
                assert pong is not None
                assert pong.ts is not None
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_button_interaction_via_auto_click(self, tmp_path: Path) -> None:
        """Display with --test-auto-click fires interaction events for buttons."""
        sock_path = tmp_path / "display.sock"

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "punt_lux",
                "display",
                "--socket",
                str(sock_path),
                "--test-auto-click",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_socket(sock_path)

            with LuxClient(sock_path, auto_spawn=False, connect_timeout=5.0) as client:
                # Send scene with 2 buttons
                ack = client.show(
                    "e2e-click-test",
                    elements=[
                        TextElement(id="t1", content="Click test"),
                        ButtonElement(id="btn-a", label="Alpha", action="alpha"),
                        ButtonElement(id="btn-b", label="Beta", action="beta"),
                    ],
                )
                assert ack is not None

                # Receive the auto-fired interaction events
                events: list[InteractionMessage] = []
                for _ in range(2):
                    msg = client.recv(timeout=5.0)
                    assert msg is not None, "Expected interaction event"
                    assert isinstance(msg, InteractionMessage)
                    events.append(msg)

                actions = {e.action for e in events}
                assert actions == {"alpha", "beta"}
                assert all(e.value is True for e in events)
        finally:
            proc.terminate()
            proc.wait(timeout=5)


@pytest.mark.e2e
def test_image_scene_fixture_path(image_scene: dict[str, object]) -> None:
    """Image scene fixture creates a valid PNG file."""
    elements = image_scene["elements"]
    assert isinstance(elements, list)
    img_element = elements[0]
    assert isinstance(img_element, dict)
    assert img_element["kind"] == "image"
    path = Path(str(img_element["path"]))
    assert path.exists()
    # Verify PNG magic bytes
    assert path.read_bytes()[:4] == b"\x89PNG"
