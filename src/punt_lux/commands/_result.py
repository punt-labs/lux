"""Shared types for the commands layer: ``CommandResult``, ``Ctx``, ``OpsPort``.

Every command in :mod:`punt_lux.commands` takes a :class:`Ctx` and returns a
:class:`CommandResult`. The four adapters -- CLI, MCP, REST, and library --
share one command singleton; each interprets the result its own way (text vs
JSON, exit code vs HTTP status vs MCP envelope).

The vox reference (``../vox/src/punt_vox/commands/_result.py``) is the shape
this module copies verbatim on :class:`CommandResult` (``frozen``, ``slots``,
four fields).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import OpError, Pong


@runtime_checkable
class OpsPort(Protocol):
    """The operations surface a command reads through.

    Every method a command calls appears here. ``Operations`` (luxd's typed
    facade) satisfies it structurally; ``LuxRestClient`` satisfies the same
    method shapes for the operations it exposes, so a CLI or library caller
    can build a :class:`Ctx` around either side of the process boundary and
    reach one shared command instance. The port widens as commands land in .3.
    """

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping bounded by ``wait`` seconds."""
        ...


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of a command invocation.

    Attributes:
        text: Human-readable output for the CLI's text mode and stderr on error.
        json_data: JSON-serializable payload for the CLI's ``--json`` mode and
            the MCP/REST envelopes. ``None`` means the CLI falls back to
            ``text``. The ``dict[str, object]`` shape is a wire boundary
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


@dataclass(frozen=True, slots=True)
class Ctx:
    """Collaborators shared by every command.

    Attributes:
        ops: The operations surface -- ``Operations`` in-process, or a client
            that structurally satisfies :class:`OpsPort` across the process
            boundary.
        identity: The caller's declared identity (DES-086). Later commands key
            store lookups by ``identity.name`` / ``identity.repo`` /
            ``identity.agent``; PingCommand does not read it, but Ctx carries
            it now so the shape is fixed before it multiplies.
    """

    ops: OpsPort
    identity: ClientIdentity
