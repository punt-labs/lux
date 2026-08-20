"""Humble Object commands for punt-lux -- one class per operation, one instance shared.

Each command is a ``@final`` callable class exported as a module-level
singleton (``ping`` and the ``scene_*`` family). Every command takes a
:class:`~punt_lux.commands._ports.Ctx` plus its own arguments and returns a
:class:`~punt_lux.commands._result.CommandResult` carrying the rendered
``text``, machine-readable ``json_data``, an ``error`` flag, and the
``exit_code`` the CLI adapter maps to ``typer.Exit``. Adapters share one
singleton per command; none re-derives the envelope.

Library callers await these directly::

    from punt_lux.commands import Ctx, ping
    ctx = Ctx(ops=..., identity=...)
    result = await ping(ctx, wait=0.5)
"""

from __future__ import annotations

from punt_lux.commands._ports import (
    CallbackOps,
    Ctx,
    FrameOps,
    MenuOps,
    PingOps,
    SceneOps,
    SessionOps,
)
from punt_lux.commands._result import CommandResult
from punt_lux.commands.callback_pending import callback_pending
from punt_lux.commands.callback_register import callback_register
from punt_lux.commands.frame_set_state import frame_set_state
from punt_lux.commands.menu_ls import menu_ls
from punt_lux.commands.menu_set import menu_set
from punt_lux.commands.ping import ping
from punt_lux.commands.scene_clear import scene_clear
from punt_lux.commands.scene_clear_all import scene_clear_all
from punt_lux.commands.scene_dashboard import scene_dashboard
from punt_lux.commands.scene_inspect import scene_inspect
from punt_lux.commands.scene_ls import scene_ls
from punt_lux.commands.scene_show import scene_show
from punt_lux.commands.scene_table import scene_table
from punt_lux.commands.scene_update import scene_update
from punt_lux.commands.session_identify import session_identify
from punt_lux.commands.session_ls import session_ls

__all__ = [
    "CallbackOps",
    "CommandResult",
    "Ctx",
    "FrameOps",
    "MenuOps",
    "PingOps",
    "SceneOps",
    "SessionOps",
    "callback_pending",
    "callback_register",
    "frame_set_state",
    "menu_ls",
    "menu_set",
    "ping",
    "scene_clear",
    "scene_clear_all",
    "scene_dashboard",
    "scene_inspect",
    "scene_ls",
    "scene_show",
    "scene_table",
    "scene_update",
    "session_identify",
    "session_ls",
]
