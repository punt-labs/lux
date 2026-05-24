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

import threading

from punt_lux.domain.element_abc import Element as DomainElement
from punt_lux.protocol.elements import element_from_dict
from punt_lux.protocol.in_memory_connection import InMemoryConnection


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
