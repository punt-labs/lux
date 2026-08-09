"""The agent-side element factory for wire decode.

Every code path that decodes a wire dict outside the Hub — the Hub's
``DisplayLink`` inbound leg, ``tools.show`` validation, the beads app, scene
message decode in ``recv_message`` / ``FrameReader.drain_typed`` — routes
through the one factory this module builds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.protocol.element_factory import JsonElementFactory
from punt_lux.protocol.elements import container_dispatch
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["NoOpAgentSideEmit", "NoOpAgentSideSink", "agent_element_factory"]


class NoOpAgentSideSink:
    """Null Object publish sink for agent-side wire decode.

    Agent-side decoders never receive publish-bearing wire elements — publish
    decorators only fire inside the luxd Hub. Any decode-time publish would
    indicate a misrouted Hub element, and agent-side validation is about schema
    integrity, not Hub-only side effects, so this sink drops it rather than
    raising.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, _topic: str, _payload: Mapping[str, object]) -> None:
        """Drop the publish — agent-side has no Hub to deliver it to."""


class NoOpAgentSideEmit:
    """Null Object emit channel for agent-side wire decode."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, _msg: object) -> None:
        """Drop the message — agent-side decode has no emit channel."""


# ``RaisingRendererFactory`` makes any accidental ``elem.render()`` from the
# agent tier loud. The decode-side container recursion is installed at import
# time, so nested containers decode through this same factory's bound method.
_AGENT_FACTORY = JsonElementFactory(
    renderer_factory=RaisingRendererFactory(),
    emit=NoOpAgentSideEmit(),
    publish_sink=cast("Any", NoOpAgentSideSink()),
)
container_dispatch.dispatch.install_from_dict(_AGENT_FACTORY.element_from_dict)


def agent_element_factory() -> JsonElementFactory:
    """Return the shared agent-side :class:`JsonElementFactory`."""
    return _AGENT_FACTORY
