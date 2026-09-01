"""Shared plumbing for the noun-grouped CLI sub-apps.

Every client-tier CLI verb routes through one commands/ singleton via a real
:class:`Ctx`. :class:`IdentityFlags` parses ``--as/--kind/--name/--repo/--agent``
into a :class:`ClientIdentity` (per-invocation identity, not privilege
elevation); :class:`OutputFlags` carries ``--json/--verbose/--quiet``.
:func:`run` drives an awaitable command to completion and maps its
:class:`CommandResult` onto stdout/stderr and the typer exit code.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import sys
from typing import TYPE_CHECKING, Annotated, Self, cast, final

import typer
from pydantic import ValidationError

from punt_lux.cli._identity_errors import describe_identity_error
from punt_lux.cli_identity import CliIdentity
from punt_lux.client.facade import LuxClient
from punt_lux.domain.hub.client_identity import ClientIdentity, ClientKind
from punt_lux.operations import Scope
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

    from punt_lux.client._sync_ops import SyncOps
    from punt_lux.commands._result import CommandResult

__all__ = [
    "AgentFlag",
    "AsFlag",
    "JsonFlag",
    "KindFlag",
    "NameFlag",
    "OutputFlags",
    "QuietFlag",
    "RepoFlag",
    "VerboseFlag",
    "connect_client",
    "identity_from_flags",
    "read_json_payload",
    "run",
    "scope_for",
]


JsonFlag = Annotated[bool, typer.Option("--json", help="Emit JSON on stdout.")]
VerboseFlag = Annotated[
    bool, typer.Option("--verbose", "-v", help="Verbose logging on stderr.")
]
QuietFlag = Annotated[
    bool, typer.Option("--quiet", "-q", help="Suppress non-JSON output.")
]

AsFlag = Annotated[
    str | None,
    typer.Option(
        "--as",
        help=(
            "Per-invocation identity as 'kind=K,name=N,repo=R,agent=A'. "
            "Per-key overrides on --kind/--name/--repo/--agent win."
        ),
    ),
]
KindFlag = Annotated[
    str | None,
    typer.Option(
        "--kind",
        help="Identity kind (cli, mcp-session, applet, app). Overrides --as kind.",
    ),
]
NameFlag = Annotated[
    str | None,
    typer.Option("--name", help="Identity display name. Overrides --as name."),
]
RepoFlag = Annotated[
    str | None,
    typer.Option(
        "--repo",
        help="Repository absolute path. Overrides --as repo. Empty string clears it.",
    ),
]
AgentFlag = Annotated[
    str | None,
    typer.Option("--agent", help="Persona handle. Overrides --as agent."),
]


@final
class OutputFlags:
    """The three global output flags every command carries."""

    _json: bool
    _verbose: bool
    _quiet: bool
    __slots__ = ("_json", "_quiet", "_verbose")

    def __new__(cls, *, json_out: bool, verbose: bool, quiet: bool) -> Self:
        self = super().__new__(cls)
        self._json = json_out
        self._verbose = verbose
        self._quiet = quiet
        return self

    @property
    def json(self) -> bool:
        return self._json

    @property
    def verbose(self) -> bool:
        return self._verbose

    @property
    def quiet(self) -> bool:
        return self._quiet

    def apply_logging(self) -> None:
        """Raise stderr log verbosity when ``--verbose`` is set."""
        if self._verbose:
            logging.basicConfig(level=logging.DEBUG)


def identity_from_flags(
    *,
    as_: str | None,
    kind: str | None,
    name: str | None,
    repo: str | None,
    agent: str | None,
) -> ClientIdentity:
    """Resolve the caller's declared identity from the identity flags.

    Absent flags fall back to :meth:`CliIdentity.resolve` — the default is the
    invocation's own working-directory-derived ``cli`` identity. Any explicit
    flag replaces the corresponding field on that default; ``--as`` supplies
    a bundle of fields under one flag, and per-key flags override it.

    Write verbs call this with the identity flags wired to real ``typer``
    options, so a caller can declare who it is for that one write. Read verbs
    (``scene ls``, ``session ls``, ``display info``, ...) call this with every
    flag ``None`` — they scope to the ambient CLI identity and take no
    identity flags of their own, because a read has no owner to declare.
    """
    parsed = _parse_as(as_)
    default = CliIdentity.resolve()
    resolved_kind = kind or parsed.get("kind") or default.kind
    resolved_name = name or parsed.get("name") or default.name
    resolved_repo = _resolve_optional(repo, parsed.get("repo"), default.repo)
    resolved_agent = _resolve_optional(agent, parsed.get("agent"), default.agent)
    try:
        return ClientIdentity(
            kind=cast("ClientKind", resolved_kind),
            name=resolved_name,
            repo=resolved_repo,
            agent=resolved_agent,
        )
    except ValidationError as exc:
        raise typer.BadParameter(describe_identity_error(exc)) from None


def _resolve_optional(
    flag: str | None, parsed: str | None, fallback: str | None
) -> str | None:
    """Merge a per-key flag over an --as-derived value over the default."""
    if flag is not None:
        return flag or None  # empty string clears
    if parsed is not None:
        return parsed
    return fallback


def _parse_as(as_: str | None) -> dict[str, str]:
    """Parse the comma-separated ``kind=K,name=N,...`` shorthand."""
    if not as_:
        return {}
    parsed: dict[str, str] = {}
    for pair in as_.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise typer.BadParameter(f"--as: expected key=value pairs; got {pair!r}")
        key, _, value = pair.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def scope_for(identity: ClientIdentity) -> Scope:
    """Compose the :class:`Scope` the identity's writes are keyed under."""
    return Scope(identity.connection_id)


def read_json_payload(inline: str | None, from_file: Path | None) -> dict[str, object]:
    """Read a JSON object from an inline string, a file, or stdin.

    Exactly one source wins: ``inline`` when given, else ``from_file``, else
    stdin (so a caller can pipe ``echo '{...}' | lux scene show s1``). A
    non-object top-level value is a usage error — every payload this reads is
    a request body, which is always a JSON object.
    """
    if inline is not None:
        raw = inline
    elif from_file is not None:
        raw = from_file.read_text()
    else:
        raw = sys.stdin.read()
    try:
        payload = _json.loads(raw)
    except _json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("payload must be a JSON object")
    return cast("dict[str, object]", payload)


def read_json_array(inline: str | None, from_file: Path | None) -> list[object]:
    """Read a JSON array from an inline string, a file, or stdin.

    Same source precedence as :func:`read_json_payload`; used by verbs whose
    body is a bare list (``menu set``'s entries array) rather than an object.
    """
    if inline is not None:
        raw = inline
    elif from_file is not None:
        raw = from_file.read_text()
    else:
        raw = sys.stdin.read()
    try:
        payload = _json.loads(raw)
    except _json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise typer.BadParameter("payload must be a JSON array")
    return cast("list[object]", payload)


def connect_client(
    *, identity: ClientIdentity | None = None, timeout: float = 2.0
) -> SyncOps:
    """Connect and return the caller's synchronous ops surface, or exit 1.

    ``identity`` must be the same :class:`ClientIdentity`
    :func:`identity_from_flags` resolved -- REST stamps its
    ``X-Lux-Client-*`` headers from it. Omitting ``identity`` falls back to
    :meth:`LuxClient.connect`'s own ambient resolution.
    """
    try:
        if identity is not None:
            return LuxClient.for_identity(identity, timeout=timeout).sync
        return LuxClient.connect(timeout=timeout).sync
    except HubUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


def run(
    coro: Coroutine[object, object, CommandResult],
    flags: OutputFlags,
) -> None:
    """Drive *coro*, render its :class:`CommandResult`, and set the exit code.

    On failure the human ``text`` goes to stderr and typer exits with the
    result's declared exit code. On success ``text`` goes to stdout, or JSON
    goes to stdout when ``--json`` is set.
    """
    flags.apply_logging()
    result = asyncio.run(coro)
    if result.error:
        if flags.json and result.json_data is not None:
            typer.echo(_json.dumps(result.json_data), err=True)
        else:
            typer.echo(result.text, err=True)
        raise typer.Exit(code=result.exit_code)
    if flags.quiet:
        return
    if flags.json and result.json_data is not None:
        typer.echo(_json.dumps(result.json_data))
    else:
        typer.echo(result.text)
