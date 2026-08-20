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

from punt_lux.commands._result import CommandResult, Ctx, PingOps, SceneOps
from punt_lux.commands.ping import ping
from punt_lux.commands.scene_clear import scene_clear
from punt_lux.commands.scene_clear_all import scene_clear_all
from punt_lux.commands.scene_dashboard import scene_dashboard
from punt_lux.commands.scene_inspect import scene_inspect
from punt_lux.commands.scene_ls import scene_ls
from punt_lux.commands.scene_show import scene_show
from punt_lux.commands.scene_table import scene_table
from punt_lux.commands.scene_update import scene_update

__all__ = [
    "CommandResult",
    "Ctx",
    "PingOps",
    "SceneOps",
    "ping",
    "scene_clear",
    "scene_clear_all",
    "scene_dashboard",
    "scene_inspect",
    "scene_ls",
    "scene_show",
    "scene_table",
    "scene_update",
]
