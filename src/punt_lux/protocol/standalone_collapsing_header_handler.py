"""Standalone ``HandlerDecoder[HeaderToggled]`` builder for CollapsingHeaderElement.

Parallel to ``standalone_checkbox_handler.py``: a collapsing header without a
parent composite model has no verb vocabulary, so the explicit factory registry
holds only ``noop``. The built-in state-sync handler (``_UpdateOpenHandler``) is
installed separately by ``JsonCollapsingHeaderDecoder`` before any wire handlers.
The decorator registry binds to whatever ``PublishSink`` the caller supplies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from punt_lux.domain.container_interaction import HeaderToggled
from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import DecoratorRegistry
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder

if TYPE_CHECKING:
    from punt_lux.domain.handlers.decorators import PublishSink

__all__ = ["build_standalone_collapsing_header_handler_decoder"]


class _NoopHeaderHandler:
    """Serializable no-op handler for ``HeaderToggled``."""

    def __call__(self, _event: HeaderToggled) -> None:
        return None


def build_standalone_collapsing_header_handler_decoder(
    sink: PublishSink,
) -> HandlerDecoder[HeaderToggled]:
    """Return the ``HandlerDecoder`` for a standalone CollapsingHeaderElement.

    Registers one explicit factory:
    - ``noop``: do-nothing handler (used when the only side effect is a
      decorator like ``publish``)

    The built-in state-sync handler is installed directly by
    ``JsonCollapsingHeaderDecoder`` so every decoded header keeps its ``open``
    flag mirrored even when the wire JSON declares no handlers.
    """
    factories: FactoryRegistry[HeaderToggled] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[HeaderToggled]:
        return _NoopHeaderHandler()

    factories.register("noop", _build_noop)
    decorators = DecoratorRegistry(sink=sink)
    return HandlerDecoder(factories=factories, decorators=decorators)
