"""The one rule for a menu-registering client's display label.

Both the display (which groups registered menu items under Applications → the
client's label) and the Hub read (``list_menus``, which must report the same
structure) derive that label the same way, from one place, so the rendered menu
and the introspected menu cannot drift apart.
"""

from __future__ import annotations

from typing import ClassVar, final


@final
class ClientLabel:
    """The display label a client's connection name resolves to."""

    # luxd's own display connection name — the one socket client the display sees,
    # so every Hub-registered menu item renders under this client's submenu.
    LUX: ClassVar[str] = "lux-mcp"

    @classmethod
    def of(cls, wire_name: str) -> str:
        """Return the human label the display shows for a client wire name.

        Strips the ``-mcp`` suffix and title-cases: ``"lux-mcp"`` -> ``"Lux"``,
        ``"vox-mcp"`` -> ``"Vox"``.
        """
        return wire_name.removesuffix("-mcp").replace("-", " ").title()
