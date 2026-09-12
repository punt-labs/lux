"""The ASCII unit separator joining a composite id's parts.

Shared by every composite id built from an owner plus a caller-chosen
string -- the Hub's menu-leaf id (``CallbackInvocation``) and
connection-scoped scene/frame id (``ConnectionScopedId``), and the
Display's own :class:`~punt_lux.display.replica.lux_address.LuxAddress`
(``hidden_id``) -- so "no agent-chosen id or hashed connection id contains
it" is proven once, in one place, not reasserted per class.

Lives directly under ``domain/`` rather than ``domain/hub/`` because it is
genuinely shared across both tiers: importing anything nested inside
``domain/hub/`` pulls in that package's ``__init__.py``, which wires the
Hub's own asyncio-resident state (``Hub``, ``HubDisplay``, the client and
writer registries) -- machinery a Display-side importer has no business
loading.
"""

from __future__ import annotations

from typing import Final

__all__ = ["ID_SEPARATOR", "NONBLANK_FRAME_ID"]

ID_SEPARATOR: Final = "\x1f"

# A leaf key an agent supplies (a callback or menu-item ``frame_id``) must be
# non-blank and free of the separator, so a stamped ``owner<US>key`` splits
# cleanly at dispatch. Shared by ``SessionCallback`` and ``MenuAction`` so the
# rule is written once. Regex, not a lookahead (pydantic-core rejects those).
NONBLANK_FRAME_ID: Final = rf"^[^{ID_SEPARATOR}]*[^{ID_SEPARATOR}\s][^{ID_SEPARATOR}]*$"
