"""``PublishSource`` — the owner a publish-on-click handler reads at click time."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from punt_lux.protocol.elements.button_publish import ButtonPublish

__all__ = ["PublishSource"]


class PublishSource(Protocol):
    """An owner whose current publish declaration is what a click publishes."""

    @property
    def publish(self) -> ButtonPublish | None:
        """Return the declaration to publish now, or None when none is declared."""
        ...
