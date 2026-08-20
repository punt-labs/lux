"""``session identify`` -- record the caller's declared identity.

Text shape matches the shipped ``identify`` MCP tool byte-for-byte --
``"identified:<name>"`` on success, the shared fault line on error.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SessionOps
    from punt_lux.operations import Scope
    from punt_lux.operations.models.identity import Identified


@final
class SessionIdentifyCommand:
    """Record the caller's declared identity against its connection."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[SessionOps],
        declaration: dict[str, object],
        *,
        scope: Scope,
    ) -> Identified | OpError:
        """Record ``declaration`` for the caller's scope, or reject a malformed one.

        The ``dict[str, object]`` shape is a wire boundary (PY-TS-14): the tool
        passes the caller's raw kind/name/repo/agent through unchanged so the
        Hub validates the shape once, at the composition boundary.
        """
        return await asyncio.to_thread(ctx.ops.identify, declaration, scope=scope)

    async def __call__(
        self,
        ctx: Ctx[SessionOps],
        declaration: dict[str, object],
        *,
        scope: Scope,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, declaration, scope=scope)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=f"identified:{result.identity.name}",
            json_data={"name": result.identity.name, "kind": result.identity.kind},
        )


session_identify: SessionIdentifyCommand = SessionIdentifyCommand()
