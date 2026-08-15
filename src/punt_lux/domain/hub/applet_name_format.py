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

The module exposes :data:`APPLET_NAME_RE` so
:class:`~punt_lux.domain.hub.client_identity.ClientIdentity` can reject a
wire-decoded applet with an unparseable name at construction. Taking a bare
``name`` string here — not a ``ClientIdentity`` — keeps the dependency arrow
pointing outward from :class:`ClientIdentity`, avoiding an import cycle.
"""

from __future__ import annotations

import re

__all__ = ["APPLET_NAME_RE", "format_name", "session_pid_from_name"]

# The write and read patterns of one format. Both fail together if the format
# changes without updating each constant here.
_SEPARATOR = " · "
_PID_PREFIX = "#"
APPLET_NAME_RE = re.compile(r"^lux · [^·]+ · #(?P<pid>[0-9a-fA-F]+) · [^·]+$")


def format_name(repo_name: str, session_pid: int, program: str) -> str:
    """Return the applet name for *repo_name*, *session_pid*, and *program*."""
    parts = ("lux", repo_name, f"{_PID_PREFIX}{session_pid:x}", program)
    return _SEPARATOR.join(parts)


def session_pid_from_name(name: str) -> int | None:
    """Return the session pid embedded in an applet's ``name``, or ``None``.

    ``None`` is the documented absence for a name that does not match the
    four-part shape. The :class:`ClientIdentity` model validator rejects a
    malformed applet name at construction, so in production this only returns
    ``None`` for callers that bypassed pydantic validation (test fixtures via
    :meth:`~pydantic.BaseModel.model_construct`, or a legacy wire payload).
    """
    match = APPLET_NAME_RE.match(name)
    return int(match.group("pid"), 16) if match is not None else None
