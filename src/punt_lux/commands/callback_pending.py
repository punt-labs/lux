"""``callback pending`` -- peek at held callback invocations without draining.

``CallbackRouter.pending`` had no adapter until now; wiring it through the
commands layer makes the peek reachable to every surface without disturbing
the delivery path (still ``take`` on the listen leg).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.commands._ports import CallbackOps, Ctx
    from punt_lux.domain.hub.session_callback import CallbackInvocation
    from punt_lux.operations import Scope


@final
class CallbackPendingCommand:
    """Return the caller's held callback invocations without clearing them."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[CallbackOps], *, scope: Scope
    ) -> tuple[CallbackInvocation, ...]:
        """Return the caller's currently-held invocations, in delivery order."""
        return ctx.ops.pending_callbacks(scope=scope)

    async def __call__(self, ctx: Ctx[CallbackOps], *, scope: Scope) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        held = await self.execute(ctx, scope=scope)
        return CommandResult(
            text=f"pending:{len(held)}",
            json_data={
                "pending": [
                    {
                        "connection_id": str(i.connection_id),
                        "callback_id": i.callback_id,
                    }
                    for i in held
                ]
            },
        )


callback_pending: CallbackPendingCommand = CallbackPendingCommand()
