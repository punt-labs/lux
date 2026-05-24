"""Text outbound end-to-end — io-model dispatch from wire dict to ABC-shaped Element.

Per docs/oo-refactor/pr3-v2.1-design.md §7(iii): commit (iii) routes Text
through ``JsonElementFactory`` so ``element_from_dict`` returns an
ABC-shaped ``TextElement`` bound to its tier's renderer factory + emit.

Commit (iv) adds ``test_in_memory_backend``: drive a Text wire payload
across the new ``InMemoryConnection`` paired-queue duplex (per §5 + D7)
without touching ``DisplayClient``. Verifies the new transport carries
the same dict shape ``element_from_dict`` accepts.
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from punt_lux.domain.element_abc import Element as DomainElement
from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements import element_from_dict
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.in_memory_connection import InMemoryConnection
from punt_lux.protocol.renderers.recording import RecordingLog, RecordingRendererFactory


def test_text_dict_decodes_to_domain_element_abc_subclass() -> None:
    elem = element_from_dict({"kind": "text", "id": "t1", "content": "Hello"})
    assert isinstance(elem, DomainElement)


def test_in_memory_backend() -> None:
    """A Text wire dict travels client → hub end through InMemoryConnection.

    Per §5: the io-model in-memory backend exposes the same
    ``send_line`` / ``iter_lines`` / ``close`` shape as ``LineSocket``.
    Per D7 (§6): this test exercises the new Connection module directly;
    it does NOT route through ``DisplayClient`` (which keeps its existing
    length-prefixed framing until a coordinated cross-tier flip).
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
    elem = element_from_dict(received[0])
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
        decoder = JsonElementFactory(renderer_factory=hub_factory, emit=lambda _m: None)

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

        assert decoded.id == original.id
        assert decoded.content == original.content
        # The decoder must bind the hub's renderer factory onto the element
        # so render() routes through the tier-local factory, not a sentinel.
        assert decoded._renderer_factory is hub_factory
        decoded.render()
        assert log.lines() == ({"op": "render", "kind": "text", "id": "t1"},)
