"""The key that says which submenu a connection contributes to.

The Clients menu groups connections into submenus by two rules, one for
applets and one for everything else. An applet is bound to a Claude Code
session, and one session may run more than one applet — ``lux-beads`` and
a tool's own applet both alive under the same process — that a person
reads as one session in the bar. Two applet connections sharing
``(repo, session_pid)`` share a submenu, so their key compares equal.
Every other kind is its own submenu, keyed by connection id.

Repo is the declared path — the same field ``menu_label`` derives its
label from — rather than ``menu_label`` itself, so a headless applet
(``repo=None``) with two siblings under one session still groups: its
``menu_label`` falls back to the four-part ``name`` (which carries the
program token and so differs between siblings), and keying on that
would split what belongs together.

The key is what the roster names and what the composition iterates
(DES-067). The prior rule — group by ``menu_label`` alone — over-fired
once two applets in one session became two distinct connections whose
repo names matched: DES-064's collision-numbering split them into ``lux``
and ``lux (2)``, when the user reads them as one session.
"""

from __future__ import annotations

import logging
from typing import Self, final

from punt_lux.domain.hub import applet_name_format
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.ids import ConnectionId

__all__ = ["MenuGroupKey"]

logger = logging.getLogger(__name__)

# The discriminator tags: one bucket for grouped applet siblings, one for
# every other kind (which always gets its own submenu).
_APPLET_TAG = "applet"
_CLIENT_TAG = "client"


@final
class MenuGroupKey:
    """The submenu one connection contributes to, hashable and comparable."""

    _payload: tuple[str, ...]
    __slots__ = ("_payload",)

    def __new__(cls, payload: tuple[str, ...]) -> Self:
        self = super().__new__(cls)
        self._payload = payload
        return self

    @classmethod
    def of(cls, connection_id: ConnectionId, identity: ClientIdentity) -> Self:
        """Return the submenu *connection_id* contributes to under *identity*.

        Applet connections in one session share a key; every other kind is
        its own. An applet whose name does not parse — construction bypassed
        the ClientIdentity model validator, or a legacy wire payload — falls
        back to per-connection grouping and logs a warning so the failure
        surfaces in luxd's log instead of a silent misgrouping.
        """
        if identity.kind == "applet":
            pid = applet_name_format.session_pid_from_name(identity.name)
            if pid is not None:
                return cls((_APPLET_TAG, identity.repo or "", format(pid, "x")))
            logger.warning(
                "connection %s (identity %r) has an unparseable applet name %r; "
                "grouping falls back to per-connection",
                connection_id,
                identity,
                identity.name,
            )
        return cls((_CLIENT_TAG, str(connection_id)))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MenuGroupKey) and self._payload == other._payload

    def __hash__(self) -> int:
        return hash((MenuGroupKey, self._payload))

    def __repr__(self) -> str:
        return f"MenuGroupKey({self._payload!r})"
