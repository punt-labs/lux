"""The shared ``CommandResult`` envelope every command returns.

Vox's ``../vox/src/punt_vox/commands/_result.py`` is the shape this module
copies verbatim: ``frozen``, ``slots``, four fields. ``Ctx`` and the
per-family ops Protocols live in :mod:`punt_lux.commands._ports`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of a command invocation.

    Attributes:
        text: Human-readable output for the CLI's text mode and stderr on error.
        json_data: JSON-serializable payload for the CLI's ``--json`` mode and
            the MCP text/envelope response. ``None`` means the CLI falls back
            to ``text``. REST does not consume this field -- it calls
            ``execute()`` for the typed result and maps it straight to an HTTP
            response via ``HttpErrorMap``, bypassing the rendered envelope
            entirely. The ``dict[str, object]`` shape is a wire boundary
            (PY-TS-14): the payload is serialized straight to JSON, so
            ``object`` is the narrowest honest static type.
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
