"""Standalone ``HandlerDecoder[RowSelectionChanged]`` builder for TableElement.

Mirrors the standalone tab-bar handler: a table without a parent composite model
has no verb vocabulary, so the explicit factory registry holds only ``noop``. The
built-in state-sync handler (``_UpdateSelectionHandler``) is installed separately
by ``JsonTableDecoder`` before any wire handlers. The decorator registry binds to
whatever ``PublishSink`` the caller supplies — that is the business-publish path
(Decision 1): a wire ``publish`` handler on ``RowSelectionChanged`` lets an agent
receive the selection as an app event.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import DecoratorRegistry
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder

if TYPE_CHECKING:
    from punt_lux.domain.handlers.publish_sink import PublishSink

__all__ = ["build_standalone_row_selection_handler_decoder"]


class _NoopRowSelectionHandler:
    """Serializable no-op handler for ``RowSelectionChanged``."""

    def __call__(self, _event: RowSelectionChanged) -> None:
        return None


def build_standalone_row_selection_handler_decoder(
    sink: PublishSink,
) -> HandlerDecoder[RowSelectionChanged]:
    """Return the ``HandlerDecoder`` for a standalone TableElement.

    Registers one explicit factory — ``noop`` — used when the only side effect is
    a decorator like ``publish``. The built-in state-sync handler is installed
    directly by ``JsonTableDecoder`` so every decoded table keeps its selection
    mirrored even when the wire JSON declares no handlers.
    """
    factories: FactoryRegistry[RowSelectionChanged] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[RowSelectionChanged]:
        return _NoopRowSelectionHandler()

    factories.register("noop", _build_noop)
    decorators = DecoratorRegistry(sink=sink)
    return HandlerDecoder(factories=factories, decorators=decorators)
