"""The callback-menu wire message — the Hub-composed session-callback bar.

Kept in its own module so the display-configuration ``menu`` module stays small:
this is the one carrier for the ``Clients`` tree the callback model
introduces, owning its own codec, while ``menu`` imports it, re-exports it, and
registers its codec alongside the agent-bar and theme messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["CallbackMenuMessage"]


@dataclass(frozen=True, slots=True)
class CallbackMenuMessage:
    """Replace the Clients menu the display renders.

    The Hub composes one submenu per live session (``{label, items: [{label,
    id}]}``) from the session registry — it owns the grouping because it owns the
    identities and leases — and re-sends the whole set on any change. The display
    replaces its copy and renders each submenu in the bar; a leaf id is a
    ``CallbackInvocation`` menu id, so a click round-trips to the owning session.
    """

    submenus: list[dict[str, Any]]  # [{label, items: [{label, id}]}]
    type: Literal["callback_menu"] = "callback_menu"

    def to_dict(self) -> dict[str, Any]:
        """Render as the wire dict the message registry transports."""
        return {"type": self.type, "submenus": self.submenus}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CallbackMenuMessage:
        """Rebuild from the wire dict.

        The Hub composes these submenus and re-sends the whole set, so the decode
        trusts the wire like the sibling menu codec rather than re-filtering it.
        """
        return cls(submenus=d.get("submenus", []))
