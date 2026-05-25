"""Text outbound end-to-end — io-model dispatch from wire dict to ABC-shaped Element.

Routes Text through ``JsonElementFactory`` so ``element_from_dict``
returns an ABC-shaped ``TextElement`` bound to its tier's renderer
factory and emit. The in-memory backend test drives a Text wire payload
across the ``InMemoryConnection`` paired-queue duplex without touching
``DisplayClient``, verifying the new transport carries the same dict
shape ``element_from_dict`` accepts.
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element_abc import Element as DomainElement
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements import build_element_codec
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.in_memory_connection import InMemoryConnection
from punt_lux.protocol.renderers.recording import RecordingLog, RecordingRendererFactory


def _no_publish(_topic: str, _payload: Mapping[str, object]) -> None:
    """Test-local publish sink — Text decode never invokes it."""


def test_text_dict_decodes_to_domain_element_abc_subclass() -> None:
    elem = agent_element_factory().element_from_dict(
        {"kind": "text", "id": "t1", "content": "Hello"}
    )
    assert isinstance(elem, DomainElement)


def test_in_memory_backend() -> None:
    """A Text wire dict travels client → hub end through InMemoryConnection.

    The in-memory backend exposes the same ``send_line`` / ``iter_lines``
    / ``close`` shape as ``LineSocket``. This test exercises the
    Connection module directly; it does NOT route through
    ``DisplayClient`` (which keeps its existing length-prefixed framing
    until a coordinated cross-tier flip).
    """
    client, hub = InMemoryConnection.paired()
    received: list[dict[str, object]] = []

    def hub_reader() -> None:
        received.extend(hub.iter_lines())

    reader_thread = threading.Thread(target=hub_reader, daemon=True)
    reader_thread.start()

    payload: dict[str, object] = {"kind": "text", "id": "t1", "content": "Hello"}
    client.send_line(payload)
    client.close()
    reader_thread.join(timeout=2.0)
    hub.close()

    assert received == [payload]
    elem = agent_element_factory().element_from_dict(received[0])
    assert isinstance(elem, DomainElement)


def test_in_memory_backend_roundtrip_with_factories() -> None:
    """Full client→hub→decode roundtrip exercising both io-model factories.

    Constructs a ``TextElement`` on the client, encodes it via
    ``JsonEncoderFactory``, ships the wire dict through an
    ``InMemoryConnection`` pair, and decodes the received payload with a
    ``JsonElementFactory`` bound to a hub-tier ``RecordingRendererFactory``.
    Confirms the decoded element preserves identity and content, that the
    injected renderer factory is the one the hub constructed, and that
    invoking ``render()`` actually routes through it.
    """
    with tempfile.TemporaryDirectory(prefix="lux-") as raw_dir:
        log = RecordingLog(Path(raw_dir) / "trace.jsonl")
        hub_factory = RecordingRendererFactory(log)
        decoder = JsonElementFactory(
            renderer_factory=hub_factory,
            emit=lambda _m: None,
            publish_sink=cast("PublishSink", _no_publish),
            codec=build_element_codec(),
        )

        original = TextElement(id="t1", content="Hello")
        encoded = JsonEncoderFactory().encode(original)

        client, hub = InMemoryConnection.paired()
        received: list[dict[str, object]] = []

        def hub_reader() -> None:
            received.extend(hub.iter_lines())

        reader_thread = threading.Thread(target=hub_reader, daemon=True)
        reader_thread.start()

        client.send_line(encoded)
        client.close()
        reader_thread.join(timeout=2.0)
        hub.close()

        assert len(received) == 1
        decoded = decoder.decode(received[0])
        assert isinstance(decoded, TextElement)

        assert decoded.id == original.id
        assert decoded.content == original.content
        # The decoder must bind the hub's renderer factory onto the element
        # so render() routes through the tier-local factory, not a sentinel.
        assert decoded._renderer_factory is hub_factory
        decoded.render()
        assert log.lines() == ({"op": "render", "kind": "text", "id": "t1"},)
