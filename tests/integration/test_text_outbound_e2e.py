"""Text outbound end-to-end — dispatch from wire dict to ABC-shaped Element.

Routes Text through ``JsonElementFactory`` so ``element_from_dict``
returns an ABC-shaped ``TextElement`` bound to its tier's renderer
factory and emit. The in-memory backend test drives a Text wire payload
across the ``InMemoryConnection`` paired-queue duplex without touching
``DisplayClient``, verifying the new transport carries the same dict
shape ``element_from_dict`` accepts.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element_abc import Element as DomainElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.in_memory_connection import InMemoryConnection
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory


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


def test_in_memory_backend_roundtrip_binds_production_di(
    real_imgui_factory: ImGuiRendererFactory,
) -> None:
    """Full client→hub→decode roundtrip asserting the real two-phase DI.

    Constructs a ``TextElement``, encodes it via ``JsonEncoderFactory``, ships
    the wire dict through an ``InMemoryConnection`` pair, and decodes it with
    the production agent-side factory. In production no tier decodes with a
    display-capable factory: the decoded element carries the fail-loud
    ``RaisingRendererFactory`` sentinel, so ``render()`` raises off the display
    tier. Only the Display's post-receive rebind binds the real
    ``ImGuiRendererFactory``, after which the factory resolves a renderer.
    """
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
    decoded = agent_element_factory().element_from_dict(received[0])
    assert isinstance(decoded, TextElement)
    assert decoded.id == original.id
    assert decoded.content == original.content

    # Production pre-rebind DI: the decode tier binds the fail-loud sentinel,
    # not a display-capable stand-in, so an off-display render() raises.
    assert isinstance(decoded._renderer_factory, RaisingRendererFactory)
    with pytest.raises(RuntimeError, match=r"cannot be rendered on this tier"):
        decoded.render()

    # Post-rebind: the Display binds the real factory, which resolves a renderer.
    decoded.bind_renderer_factory(real_imgui_factory)
    assert isinstance(decoded._renderer_factory(decoded), ImGuiTextRenderer)
