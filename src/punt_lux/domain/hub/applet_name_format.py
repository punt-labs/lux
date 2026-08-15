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

from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["format_name", "session_pid_of"]

_SEPARATOR = " · "
_PID_PART_INDEX = 2
_PID_PART_PREFIX = "#"
_PART_COUNT = 4


def format_name(repo_name: str, session_pid: int, program: str) -> str:
    """Return the applet name for *repo_name*, *session_pid*, and *program*."""
    parts = ("lux", repo_name, f"{_PID_PART_PREFIX}{session_pid:x}", program)
    return _SEPARATOR.join(parts)


def session_pid_of(client: ClientIdentity) -> int | None:
    """Return the applet's session pid, or ``None`` for a non-applet.

    Only an applet is named ``lux · <repo> · #<pid> · <program>``, so a
    non-applet returns ``None`` — the documented absence the menu-grouping
    composer skips on. An applet whose name does not parse raises
    :class:`ValueError` rather than silently mis-group.
    """
    if client.kind != "applet":
        return None
    parts = client.name.split(_SEPARATOR)
    pid_part = parts[_PID_PART_INDEX] if len(parts) == _PART_COUNT else ""
    try:
        return int(pid_part.removeprefix(_PID_PART_PREFIX), 16)
    except ValueError as exc:
        msg = f"malformed applet name: {client.name!r}"
        raise ValueError(msg) from exc
