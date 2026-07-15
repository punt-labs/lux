"""Standalone ``HandlerDecoder[ValueChanged]`` builder for SliderElement.

Parallel to ``standalone_input_text_handler.py``: a slider without a parent
composite model has no verb vocabulary, so the explicit factory registry
contains only ``noop``. The built-in state-sync handler (``_UpdateValueHandler``)
is installed separately by ``JsonSliderDecoder`` before any wire-declared
handlers are decoded. The decorator registry binds to whatever ``PublishSink``
the caller supplies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, final

from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import DecoratorRegistry
from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder

if TYPE_CHECKING:
    from punt_lux.domain.handlers.decorators import PublishSink

__all__ = ["build_standalone_slider_handler_decoder"]


@final
class _NoopValueHandler:
    """Serializable no-op handler for ``ValueChanged``."""

    def __call__(self, _event: ValueChanged) -> None:
        return None


def build_standalone_slider_handler_decoder(
    sink: PublishSink,
) -> HandlerDecoder[ValueChanged]:
    """Return the ``HandlerDecoder`` for a standalone SliderElement.

    Registers only the ``noop`` factory — a do-nothing handler for when the
    sole side effect is a decorator like ``publish``. The built-in state-sync
    handler is installed directly by ``JsonSliderDecoder`` so every decoded
    slider keeps its value mirrored even when the wire JSON declares none.
    """
    factories: FactoryRegistry[ValueChanged] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[ValueChanged]:
        return _NoopValueHandler()

    factories.register("noop", _build_noop)
    decorators = DecoratorRegistry(sink=sink)
    return HandlerDecoder(factories=factories, decorators=decorators)
