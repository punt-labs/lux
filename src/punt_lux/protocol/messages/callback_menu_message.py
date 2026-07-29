"""The callback-menu wire message — the Hub-composed session-callback bar.

Kept in its own module so the display-configuration ``menu`` module stays at its
three legacy menu messages; this is the one carrier for the session-then-callback
tree the callback model introduces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["CallbackMenuMessage"]


@dataclass(frozen=True, slots=True)
class CallbackMenuMessage:
    """Replace the session-then-callback submenus the display renders.

    The Hub composes one submenu per live session (``{label, items: [{label,
    id}]}``) from the session registry — it owns the grouping because it owns the
    identities and leases — and re-sends the whole set on any change. The display
    replaces its copy and renders each submenu in the bar; a leaf id is a
    ``CallbackInvocation`` menu id, so a click round-trips to the owning session.
    """

    submenus: list[dict[str, Any]]  # [{label, items: [{label, id}]}]
    type: Literal["callback_menu"] = "callback_menu"
