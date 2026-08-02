"""Standalone ``HandlerDecoder[ModalClosed]`` builder for ModalElement.

Mirrors the collapsing-header builder: a modal without a parent composite model
has no verb vocabulary, so the explicit factory registry holds only ``noop``. The
built-in dismiss handler that drives ``model.close`` is installed separately by
``JsonModalDecoder`` before any wire handlers. The decorator registry binds to
whatever ``PublishSink`` the caller supplies, so an agent's ``publish``-decorated
close handler reaches a real channel.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from punt_lux.domain.container_interaction import ModalClosed
from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import DecoratorRegistry
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder

if TYPE_CHECKING:
    from punt_lux.domain.handlers.publish_sink import PublishSink

__all__ = ["build_standalone_modal_handler_decoder"]


class _NoopModalHandler:
    """Serializable no-op handler for ``ModalClosed``."""

    def __call__(self, _event: ModalClosed) -> None:
        return None


def build_standalone_modal_handler_decoder(
    sink: PublishSink,
) -> HandlerDecoder[ModalClosed]:
    """Return the ``HandlerDecoder`` for a standalone ModalElement.

    Registers one explicit factory:
    - ``noop``: do-nothing handler (used when the only side effect is a
      decorator like ``publish``)

    The built-in dismiss handler is installed directly by ``JsonModalDecoder`` so
    every decoded modal removes itself on close even when the wire JSON declares
    no handlers.
    """
    factories: FactoryRegistry[ModalClosed] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[ModalClosed]:
        return _NoopModalHandler()

    factories.register("noop", _build_noop)
    decorators = DecoratorRegistry(sink=sink)
    return HandlerDecoder(factories=factories, decorators=decorators)
