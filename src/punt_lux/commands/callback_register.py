"""``callback register`` -- register a menu callback for the caller's session.

Text shape matches the shipped ``register_callback`` MCP tool byte-for-byte --
``"registered:<callback_id>"`` on success and ``"error: <reason>"`` on either
of the two preconditions (identity, push-reachable leg) failing. The success
line falls back to the request's own callback id -- an ``Ok`` reply carries no
payload, so the id the caller passed in is the id the caller reads back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult
from punt_lux.operations import Ok, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import CallbackOps, Ctx
    from punt_lux.operations import Scope
    from punt_lux.operations.models.callbacks import RegisterCallbackRequest


@final
class CallbackRegisterCommand:
    """Register the caller's menu callback and push the updated bar."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[CallbackOps],
        request: RegisterCallbackRequest | OpError,
        *,
        scope: Scope,
    ) -> Ok | OpError:
        """Register ``request`` for the caller's scope and return the typed outcome."""
        return ctx.ops.register_callback(request, scope=scope)

    async def __call__(
        self,
        ctx: Ctx[CallbackOps],
        request: RegisterCallbackRequest | OpError,
        callback_id: str,
        *,
        scope: Scope,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope.

        ``callback_id`` is the caller's own name for the callback -- the ``Ok``
        reply carries no payload, so echoing the caller's id back is what
        ``"registered:<id>"`` has always meant.
        """
        result = await self.execute(ctx, request, scope=scope)
        if isinstance(result, OpError):
            return CommandResult(
                text=f"error: {result.reason}",
                json_data={"code": result.code, "reason": result.reason},
                error=True,
                exit_code=1,
            )
        return CommandResult(
            text=f"registered:{callback_id}",
            json_data={"callback_id": callback_id},
        )


callback_register: CallbackRegisterCommand = CallbackRegisterCommand()
