"""Fail-closed gate for menu/callback-menu/theme content (bead lux-2kv9 / W1).

An unidentified fd -- one that never sent a ``ConnectMessage`` -- has no
attribution to install content under and is rejected uniformly, the same
invariant :class:`~punt_lux.display.identity_guard.IdentityGuard` enforces
for scenes. This is where that check lives for the three non-scene
content-bearing message kinds, so ``RenderLoop._handle_message`` stays a
pure dispatch table instead of re-deriving the same fd-extraction
boilerplate three times.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.hub_reconciliation import HubReconciliation
    from punt_lux.display.replica.menu_replica import MenuReplica
    from punt_lux.protocol import CallbackMenuMessage, MenuMessage, ThemeMessage

__all__ = ["ContentMessageGate"]


class ContentMessageGate:
    """Install menu/callback-menu/theme content only from an identified fd."""

    _menus: MenuReplica
    _apply_theme: Callable[[str], None]
    _hub_reconciliation: HubReconciliation

    def __new__(
        cls,
        menus: MenuReplica,
        apply_theme: Callable[[str], None],
        hub_reconciliation: HubReconciliation,
    ) -> Self:
        self = super().__new__(cls)
        self._menus = menus
        self._apply_theme = apply_theme
        self._hub_reconciliation = hub_reconciliation
        return self

    def handle_agent_menus(self, sock: socket.socket, msg: MenuMessage) -> None:
        """Install the Hub's agent-menu tree; reject an unidentified sender."""
        if not self._reject_if_unidentified(sock, "MenuMessage"):
            self._menus.replace_agent_menus(msg.menus)

    def handle_callback_menus(
        self, sock: socket.socket, msg: CallbackMenuMessage
    ) -> None:
        """Install the Hub's callback-menu tree; reject an unidentified sender."""
        if not self._reject_if_unidentified(sock, "CallbackMenuMessage"):
            self._menus.replace_callback_menus(msg.submenus)

    def handle_theme(self, sock: socket.socket, msg: ThemeMessage) -> None:
        """Apply the Hub's theme selection; reject an unidentified sender."""
        if not self._reject_if_unidentified(sock, "ThemeMessage"):
            self._apply_theme(msg.theme)

    def _reject_if_unidentified(self, sock: socket.socket, message_kind: str) -> bool:
        try:
            fd = sock.fileno()
        except OSError:
            return True
        return self._hub_reconciliation.reject_if_unidentified(fd, message_kind)
