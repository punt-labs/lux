"""``CommandResult`` -- the outcome envelope every command hands back.

Every command in :mod:`punt_lux.commands` takes a
:class:`~punt_lux.commands._ctx.Ctx` and returns a :class:`CommandResult`.
The four adapters -- CLI, MCP, REST, and library -- share one command
singleton; each interprets the result its own way (text vs JSON, exit code
vs HTTP status vs MCP envelope).

The vox reference (``../vox/src/punt_vox/commands/_result.py``) is the shape
this module copies verbatim on :class:`CommandResult` (``frozen``, ``slots``,
four fields).

:class:`~punt_lux.commands._ops_port.OpsPort` and
:class:`~punt_lux.commands._ctx.Ctx` live in their own modules -- the port is
a family contract, ``Ctx`` is the per-call collaborator bundle, and this
module's only job is the result shape a command produces. Both are
re-exported here so the rest of the commands layer keeps one import path.
"""

from __future__ import annotations

from dataclasses import dataclass

from punt_lux.commands._ctx import Ctx
from punt_lux.commands._ops_port import OpsPort

__all__ = ["CommandResult", "Ctx", "OpsPort"]


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of a command invocation.

    Attributes:
        text: Human-readable output for the CLI's text mode and stderr on error.
        json_data: JSON-serializable payload for the CLI's ``--json`` mode and
            the MCP text/envelope response. ``None`` means the CLI falls back
            to ``text``. REST does not consume this field -- it calls
            ``execute()`` for the typed ``Pong | OpError`` result and maps it
            straight to an HTTP response via ``HttpErrorMap``, bypassing the
            rendered envelope entirely. The ``dict[str, object]`` shape is a
            wire boundary (PY-TS-14): the payload is serialized straight to
            JSON, so ``object`` is the narrowest honest static type.
        error: ``True`` signals a user-facing failure (invalid input, missing
            resource, daemon unreachable). Adapters route through their own
            error channel (stderr for CLI, HTTP status for REST, error
            envelope for MCP) and exit with ``exit_code``. Programmer errors
            and violated invariants still raise per punt-kit Error Handling.
        exit_code: The process exit code the CLI adapter emits when ``error``
            is ``True``. Ignored on success. Convention: ``1`` for user-facing
            failures, matching the daemon-error and MCP-tool envelope shapes.
    """

    text: str
    # dict[str, object]: PY-TS-14 wire-boundary -- serialized directly to JSON.
    json_data: dict[str, object] | None = None
    error: bool = False
    exit_code: int = 0
