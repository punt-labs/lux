"""Standalone ``HandlerDecoder[ValueChanged]`` builder for CheckboxElement.

Parallel to ``standalone_button_handler.py``: a checkbox without a parent
composite model has no verb vocabulary, so the explicit factory registry
contains only ``noop``. The built-in state-sync handler
(``_UpdateValueHandler``) is installed separately by ``JsonCheckboxDecoder``
before any wire-declared handlers are decoded. The decorator registry binds
to whatever ``PublishSink`` the caller supplies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import DecoratorRegistry
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder

if TYPE_CHECKING:
    from punt_lux.domain.handlers.decorators import PublishSink

__all__ = ["build_standalone_checkbox_handler_decoder"]


class _NoopValueHandler:
    """Serializable no-op handler for ``ValueChanged``."""

    def __call__(self, _event: ValueChanged) -> None:
        return None


def build_standalone_checkbox_handler_decoder(
    sink: PublishSink,
) -> HandlerDecoder[ValueChanged]:
    """Return the ``HandlerDecoder`` for a standalone CheckboxElement.

    Registers one explicit factory:
    - ``noop``: do-nothing handler (used when the only side effect is a
      decorator like ``publish``)

    The built-in state-sync handler is installed directly by
    ``JsonCheckboxDecoder`` so every decoded checkbox keeps its boolean value
    mirrored even when the wire JSON does not declare any handlers.
    """
    factories: FactoryRegistry[ValueChanged] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[ValueChanged]:
        return _NoopValueHandler()

    factories.register("noop", _build_noop)
    decorators = DecoratorRegistry(sink=sink)
    return HandlerDecoder(factories=factories, decorators=decorators)
