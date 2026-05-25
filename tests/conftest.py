"""Shared test fixtures for punt-lux."""

from __future__ import annotations

import socket
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast

import pytest

from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements import build_element_codec
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from collections.abc import Generator


class _TestRecordingSink:
    """Publish sink that records every ``(topic, payload)`` for assertions.

    Tests that need to assert no-publish (or to inspect what was
    published during decode) construct one of these and read
    ``self.calls``. Lives in ``tests/`` because production code has no
    business knowing about recording sinks.
    """

    __slots__ = ("calls",)

    calls: list[tuple[str, Mapping[str, object]]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.calls = []
        return self

    def __call__(self, topic: str, payload: Mapping[str, object]) -> None:
        """Record the publish — tests assert on ``self.calls``."""
        self.calls.append((topic, payload))


def _build_test_factory(sink: _TestRecordingSink | None = None) -> JsonElementFactory:
    """Build a :class:`JsonElementFactory` wired with a recording sink."""

    def _no_op_emit(_msg: object) -> None:
        """Emit channel that drops events — tests don't assert against it."""

    return JsonElementFactory(
        renderer_factory=RaisingRendererFactory(),
        emit=_no_op_emit,
        publish_sink=cast("Any", sink or _TestRecordingSink()),
        codec=build_element_codec(),
    )


@pytest.fixture
def element_factory() -> JsonElementFactory:
    """Return a :class:`JsonElementFactory` wired with a recording sink."""
    return _build_test_factory()


@pytest.fixture
def recording_sink() -> _TestRecordingSink:
    """Return a fresh :class:`_TestRecordingSink` for direct construction."""
    return _TestRecordingSink()


# ---------------------------------------------------------------------------
# Sample scene data
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_scene() -> dict[str, object]:
    """Minimal valid scene with one text element."""
    return {
        "type": "scene",
        "id": "test-scene-001",
        "layout": "rows",
        "elements": [
            {
                "kind": "text",
                "id": "txt-hello",
                "content": "Hello from Lux",
                "style": "heading",
            },
        ],
    }


@pytest.fixture
def interactive_scene() -> dict[str, object]:
    """Scene with interactive controls that generate events."""
    return {
        "type": "scene",
        "id": "test-scene-002",
        "layout": "rows",
        "elements": [
            {
                "kind": "text",
                "id": "title",
                "content": "Test Panel",
                "style": "heading",
            },
            {
                "kind": "slider",
                "id": "slider-temp",
                "label": "Temperature",
                "value": 50.0,
                "min": 0.0,
                "max": 100.0,
            },
            {
                "kind": "checkbox",
                "id": "chk-enable",
                "label": "Enable",
                "value": True,
            },
            {
                "kind": "button",
                "id": "btn-submit",
                "label": "Submit",
                "action": "submit",
            },
        ],
    }


@pytest.fixture
def image_scene(tmp_path: Path) -> dict[str, object]:
    """Scene with an image element pointing to a temp file."""
    img_path = tmp_path / "test.png"
    # 1x1 white PNG (minimal valid PNG)
    img_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
        b"\x00\x00\x00IEND\xaeB`\x82"
    )
    return {
        "type": "scene",
        "id": "test-scene-img",
        "layout": "single",
        "elements": [
            {
                "kind": "image",
                "id": "img-test",
                "path": str(img_path),
                "alt": "Test image",
                "width": 100,
                "height": 100,
            },
            {
                "kind": "button",
                "id": "btn-approve",
                "label": "Approve",
                "action": "approve",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Socket fixtures for integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def socket_pair() -> Generator[tuple[socket.socket, socket.socket]]:
    """Create a connected Unix domain socket pair for testing IPC."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = Path(tmpdir) / "test.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(sock_path))
        conn, _ = server.accept()

        try:
            yield client, conn
        finally:
            client.close()
            conn.close()
            server.close()
