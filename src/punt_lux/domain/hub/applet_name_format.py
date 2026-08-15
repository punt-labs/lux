"""The applet ``name`` format the Hub reads back from a declared identity.

An applet identifies itself with ``lux · <repo> · #<pid> · <program>``: the tool,
the repository, the session that declared it, and the program that runs there.
The Hub needs to read the pid back to know when two applet connections belong
to one session (:class:`~punt_lux.domain.hub.menu_group_key.MenuGroupKey`), so
the parse lives in the domain layer where the reader is. The writer —
:meth:`~punt_lux.applets.identity.AppletIdentity.for_session` — delegates to
:func:`format_name` here so both halves change together, and the round-trip
test in ``tests/applets/test_identity.py`` fails loud if either half moves
alone.
"""

from __future__ import annotations

import re

from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["format_name", "session_pid_of"]

# The write and read patterns of one format. Both fail together if the format
# changes without updating each constant here.
_SEPARATOR = " · "
_PID_PREFIX = "#"
_APPLET_NAME_RE = re.compile(r"^lux · [^·]+ · #(?P<pid>[0-9a-fA-F]+) · [^·]+$")


def format_name(repo_name: str, session_pid: int, program: str) -> str:
    """Return the applet name for *repo_name*, *session_pid*, and *program*."""
    parts = ("lux", repo_name, f"{_PID_PREFIX}{session_pid:x}", program)
    return _SEPARATOR.join(parts)


def session_pid_of(client: ClientIdentity) -> int | None:
    """Return the applet's session pid, or ``None`` when it carries none.

    ``None`` covers the two absences that both mean "no session grouping":
    a non-applet kind (which is never named ``lux · <repo> · #<pid> ·
    <program>``), and an applet whose declared name does not parse. The
    grouping composer treats both the same way — the connection is its own
    submenu — so a pre-format applet identity does not crash the menu.
    """
    if client.kind != "applet":
        return None
    match = _APPLET_NAME_RE.match(client.name)
    return int(match.group("pid"), 16) if match is not None else None
