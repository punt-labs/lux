"""Standalone ``HandlerDecoder[ButtonClicked]`` builder for top-level Buttons.

A standalone Button (one without a parent Dialog model) has no verb
vocabulary to resolve ``call_model`` against, so only the ``noop`` inner
factory is registered. The decorator registry binds to whatever
``PublishSink`` the caller supplies — at a real tier that's the
Hub-bound sink; at the no-tier boundary that's a ``RaisingPublishSink``.

Both ``ButtonElement.from_dict`` (the test/agent ad-hoc decode path)
and ``JsonElementFactory`` (the per-tier dispatcher) reach for this
same helper — the registry shape is identical; only the sink differs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers import ButtonHandlers, DecoratorRegistry
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder

if TYPE_CHECKING:
    from punt_lux.domain.handlers.decorators import PublishSink

__all__ = ["build_standalone_button_handler_decoder"]


def build_standalone_button_handler_decoder(
    sink: PublishSink,
) -> HandlerDecoder[ButtonClicked]:
    """Return the noop-only ``HandlerDecoder`` for a Button without a parent model.

    The ``sink`` parameter is the ``PublishSink`` the decorator registry
    fans ``publish`` decorators out to. Pass a Hub-bound sink at the
    tier boundary; pass a ``RaisingPublishSink`` for the no-tier
    fallback so a stray publish surfaces loud.
    """
    factories: FactoryRegistry[ButtonClicked] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[ButtonClicked]:
        return ButtonHandlers.noop()

    factories.register("noop", _build_noop)
    decorators = DecoratorRegistry(sink=sink)
    return HandlerDecoder(factories=factories, decorators=decorators)
