"""``lux callback register`` — register a menu callback for the caller's session.

``callback pending`` has no REST route by ratified design
(``tests/rest/test_app.py`` ``_MCP_ONLY``): a stateless REST request cannot
bind to the listen leg's ``take`` drain that delivers it, so no REST-backed
CLI verb can exist. Not shipped here; not a gap in this mission's scope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

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
    connect_client,
    identity_from_flags,
    run,
    scope_for,
)
from punt_lux.commands import CallbackRegisterOps, Ctx, callback_register
from punt_lux.operations import OpError
from punt_lux.operations.models.callback_fields import CallbackFields
from punt_lux.operations.models.callbacks import RegisterCallbackRequest

if TYPE_CHECKING:
    from punt_lux.client._callback_ops import CallbackConvenienceOps
    from punt_lux.operations import Ok, Scope

callback_app = typer.Typer(
    name="callback",
    help="Register a menu callback for the caller's session.",
    no_args_is_help=True,
)

__all__ = ["callback_app"]


@final
class _CallbackRegisterAdapter:
    """Satisfies ``CallbackRegisterOps`` over the transport's convenience shape.

    ``register_callback(callback_id, label)`` is a convenience shape
    production callers (``applets/leg.py``) already depend on; this command
    needs the Protocol's ``(request, *, scope)`` shape instead. A small
    adapter here avoids changing the shipped convenience method's signature
    under existing callers.
    """

    _client: CallbackConvenienceOps
    __slots__ = ("_client",)

    def __new__(cls, client: CallbackConvenienceOps) -> Self:
        self = super().__new__(cls)
        self._client = client
        return self

    def register_callback(
        self, request: RegisterCallbackRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        del scope  # REST composes scope from headers, not this parameter
        if isinstance(request, OpError):
            return request
        return self._client.register_callback(
            request.callback.id, request.callback.label
        )


@callback_app.command("register")
def register(
    callback_id: str = typer.Argument(help="Opaque callback id the caller owns."),
    label: str = typer.Argument(help="Menu label the callback appears under."),
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
    """Register a menu callback the caller's session will receive clicks on."""
    flags = OutputFlags(json_out=json_out, verbose=verbose, quiet=quiet)
    identity = identity_from_flags(
        as_=as_, kind=kind, name=name, repo=repo, agent=agent
    )
    request = RegisterCallbackRequest.parse(CallbackFields(callback_id, label))
    ops = _CallbackRegisterAdapter(connect_client(identity=identity))
    ctx: Ctx[CallbackRegisterOps] = Ctx(ops=ops, identity=identity)
    run(callback_register(ctx, request, scope=scope_for(identity)), flags)
