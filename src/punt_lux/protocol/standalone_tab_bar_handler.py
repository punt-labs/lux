"""Standalone ``HandlerDecoder[TabChanged]`` builder for TabBarElement.

Parallel to ``standalone_checkbox_handler.py``: a tab bar without a parent
composite model has no verb vocabulary, so the explicit factory registry holds
only ``noop``. The built-in state-sync handler (``_UpdateActiveTabHandler``) is
installed separately by ``JsonTabBarDecoder`` before any wire handlers. The
decorator registry binds to whatever ``PublishSink`` the caller supplies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from punt_lux.domain.container_interaction import TabChanged
from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import DecoratorRegistry
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder

if TYPE_CHECKING:
    from punt_lux.domain.handlers.decorators import PublishSink

__all__ = ["build_standalone_tab_bar_handler_decoder"]


class _NoopTabHandler:
    """Serializable no-op handler for ``TabChanged``."""

    def __call__(self, _event: TabChanged) -> None:
        return None


def build_standalone_tab_bar_handler_decoder(
    sink: PublishSink,
) -> HandlerDecoder[TabChanged]:
    """Return the ``HandlerDecoder`` for a standalone TabBarElement.

    Registers one explicit factory:
    - ``noop``: do-nothing handler (used when the only side effect is a
      decorator like ``publish``)

    The built-in state-sync handler is installed directly by ``JsonTabBarDecoder``
    so every decoded tab bar keeps its ``active_tab`` mirrored even when the wire
    JSON declares no handlers.
    """
    factories: FactoryRegistry[TabChanged] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[TabChanged]:
        return _NoopTabHandler()

    factories.register("noop", _build_noop)
    decorators = DecoratorRegistry(sink=sink)
    return HandlerDecoder(factories=factories, decorators=decorators)
