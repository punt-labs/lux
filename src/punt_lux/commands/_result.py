"""Shared types for the commands layer: ``CommandResult``, ``Ctx``, and ops families.

Every command in :mod:`punt_lux.commands` takes a :class:`Ctx` and returns a
:class:`CommandResult`. The four adapters -- CLI, MCP, REST, and library -- share
one command singleton; each interprets the result its own way (text vs JSON,
exit code vs HTTP status vs MCP envelope).

The vox reference (``../vox/src/punt_vox/commands/_result.py``) is the shape
this module copies verbatim on :class:`CommandResult` (``frozen``, ``slots``,
four fields).

``Ctx`` is generic over the ops surface a command reads (``Ctx[SceneOps]``,
``Ctx[PingOps]``, ...). One flat ``OpsPort`` covering every operation would force
every transport that builds a ``Ctx`` to implement every family, even the ones it
never calls: ``LuxRestClient`` satisfies ``PingOps`` (one method) for the CLI's
``ping``, and would fail to satisfy a widened all-in-one protocol the moment scene
or menu methods joined it. Splitting by family -- one small Protocol per noun --
keeps each transport honest about what it actually implements and keeps each
command's stub test small (PL-TT-5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import (
        Cleared,
        InspectScope,
        OpError,
        Pong,
        RenderDashboardRequest,
        RenderRequest,
        RenderTableRequest,
        SceneInspection,
        SceneList,
        SceneShown,
        Scope,
        UpdateRequest,
    )


@runtime_checkable
class PingOps(Protocol):
    """The ops surface :mod:`punt_lux.commands.ping` reads."""

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping bounded by ``wait`` seconds."""
        ...


@runtime_checkable
class SceneOps(Protocol):
    """The ops surface the scene commands read.

    ``Operations`` (luxd's typed facade) is the sole production implementer --
    every scene command runs in-process inside luxd, so no remote transport needs
    to satisfy this family the way ``LuxRestClient`` satisfies ``PingOps``.
    """

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Install a whole scene."""
        ...

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch to a scene."""
        ...

    def clear_scene(self, *, scope: Scope, scene_id: str) -> Cleared | OpError:
        """Clear just ``scene_id``."""
        ...

    def clear(self, *, scope: Scope) -> Cleared | OpError:
        """Clear every scene the caller owns."""
        ...

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Render a filterable table scene."""
        ...

    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Render a dashboard scene."""
        ...

    def inspect_scene(
        self, scene_id: str, *, scope: Scope, facts: InspectScope
    ) -> SceneInspection | OpError:
        """Return the caller's own scene tree."""
        ...

    def list_scenes(self) -> SceneList:
        """List every live scene and frame from the authoritative store."""
        ...


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


@dataclass(frozen=True, slots=True)
class Ctx[OpsT]:
    """Collaborators shared by every command.

    Attributes:
        ops: The ops family surface this command reads -- narrowed per command
            (``Ctx[SceneOps]``, ``Ctx[PingOps]``, ...) so a stub test and a
            remote transport each need only satisfy the family they touch.
            ``Ctx`` is invariant in ``OpsT`` (PEP 695 gives no variance
            keyword), so build it either inline as a call argument or with an
            explicit ``Ctx[SomeOps]`` annotation on the assignment -- both let
            the type checker infer ``OpsT`` from the expected type rather than
            from the wider concrete type of the value passed in.
        identity: The caller's declared identity (DES-086). Store lookups key
            by ``identity.name`` / ``identity.repo`` / ``identity.agent``.
    """

    ops: OpsT
    identity: ClientIdentity
