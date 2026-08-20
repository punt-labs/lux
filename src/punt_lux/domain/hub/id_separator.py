"""The ASCII unit separator joining a connection id to a caller-local label.

Shared by every composite wire-adjacent id the Hub derives from a connection
plus a caller-chosen string — the menu-leaf id (``CallbackInvocation``) and the
connection-scoped scene/frame id (``ConnectionScopedId``) both import this one
constant, so "no agent-chosen id or hashed connection id contains it" is
proven once, in one place, not reasserted per class.
"""

from __future__ import annotations

from typing import Final

__all__ = ["ID_SEPARATOR"]

ID_SEPARATOR: Final = "\x1f"
