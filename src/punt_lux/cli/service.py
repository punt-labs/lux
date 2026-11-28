"""``lux service register|ls`` -- register what a client serves, list who serves.

``register`` needs a live listen leg on the caller's identity, so it succeeds
only from a long-lived client; a one-shot command is refused with
``push_required``. ``ls`` is a read: it scopes to the ambient CLI identity and
takes no identity flags.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from punt_lux.cli._shared import (
    AgentFlag,
    AsFlag,
    JsonFlag,
    KindFlag,
    NameFlag,
    OutputFlags,
    QuietFlag,
    RepoFlag,
    VerboseFlag,
    connect_service,
    identity_from_flags,
    run,
    scope_for,
)
from punt_lux.commands import Ctx
from punt_lux.commands.service_ls import service_ls
from punt_lux.commands.service_register import service_register
from punt_lux.wire.operations.service_requests import RegisterServiceRequest

if TYPE_CHECKING:
    from punt_lux.wire.model.client_identity import ClientIdentity
    from punt_lux.wire.ops import ServiceOps

__all__ = ["service_app"]


class ServiceCommands:
    """The ``lux service`` verbs, registered on :data:`service_app`."""

    @staticmethod
    def _output(json_out: bool, verbose: bool, quiet: bool) -> OutputFlags:
        return OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)

    @staticmethod
    def _ctx(identity: ClientIdentity) -> Ctx[ServiceOps]:
        return Ctx(ops=connect_service(identity=identity), identity=identity)

    @staticmethod
    def register(
        service: str = typer.Argument(help="Name of the service the caller serves."),
        *,
        as_: AsFlag = None,
        kind: KindFlag = None,
        name: NameFlag = None,
        repo: RepoFlag = None,
        agent: AgentFlag = None,
        json_out: JsonFlag = False,
        verbose: VerboseFlag = False,
        quiet: QuietFlag = False,
    ) -> None:
        """Register the service the caller's session serves on its listen leg."""
        flags = ServiceCommands._output(json_out, verbose, quiet)
        identity = identity_from_flags(
            as_=as_, kind=kind, name=name, repo=repo, agent=agent
        )
        ctx = ServiceCommands._ctx(identity)
        request = RegisterServiceRequest.parse(service)
        run(service_register(ctx, request, scope=scope_for(identity)), flags)

    @staticmethod
    def ls(
        *,
        json_out: JsonFlag = False,
        verbose: VerboseFlag = False,
        quiet: QuietFlag = False,
    ) -> None:
        """List which hosts serve which services."""
        flags = ServiceCommands._output(json_out, verbose, quiet)
        identity = identity_from_flags(
            as_=None, kind=None, name=None, repo=None, agent=None
        )
        run(
            service_ls(ServiceCommands._ctx(identity), scope=scope_for(identity)), flags
        )


service_app = typer.Typer(
    name="service",
    help="Register what this client serves, and list who serves what.",
    no_args_is_help=True,
)
service_app.command("register")(ServiceCommands.register)
service_app.command("ls")(ServiceCommands.ls)
