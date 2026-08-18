"""Humble Object commands for punt-lux -- one class per operation, one instance shared.

Each command is a ``@final`` callable class exported as a module-level
singleton (``ping`` and, in .3, ``scene_show`` / ``frame_raise`` / ...). Every
command takes a :class:`~punt_lux.commands._result.Ctx` plus its own arguments
and returns a :class:`~punt_lux.commands._result.CommandResult` carrying the
rendered ``text``, machine-readable ``json_data``, an ``error`` flag, and the
``exit_code`` the CLI adapter maps to ``typer.Exit``.

The four adapters (CLI, MCP, REST, library) share one singleton per command;
none re-derives the result envelope.

Library callers await these directly::

    from punt_lux.commands import Ctx, ping
    ctx = Ctx(ops=..., identity=...)
    result = await ping(ctx, wait=0.5)
    print(result.text)
    # result.exit_code is 0 on success, 1 on an expected user error.
"""

from __future__ import annotations

from punt_lux.commands._result import CommandResult, Ctx, OpsPort
from punt_lux.commands.ping import ping

__all__ = [
    "CommandResult",
    "Ctx",
    "OpsPort",
    "ping",
]
