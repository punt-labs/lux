"""Keep MCP checkout selection separate from Hub registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from punt_lux.service.repo_activation import Checkout
from punt_lux.tools._repo_roots import RepoRoots

if TYPE_CHECKING:
    from fastmcp import Context

    from punt_lux.service.repo_activation import ActivationState
    from punt_lux.wire.model.client_identity import ClientIdentity

_SELECTION = "lux:repo-selection"


@dataclass(frozen=True, slots=True)
class RepoSelection:
    context: Context | None

    async def off_state(
        self, declared: object, identity: ClientIdentity | None
    ) -> ActivationState | None:
        selected = identity.repo if identity is not None else await self._selection()
        target = self._checkout(declared) or self._checkout(selected)
        roots = await RepoRoots(self._session_context).advertised()
        root = roots[0] if roots and target not in roots else None
        for checkout in (root, target):
            if checkout is not None and not (state := checkout.state()).enabled:
                await self._remember_selection(identity)
                return state
        return None

    @property
    def _session_context(self) -> Context | None:
        ctx = self.context
        return ctx if ctx is not None and ctx.request_context is not None else None

    async def _selection(self) -> object:
        ctx = self._session_context
        return await ctx.get_state(_SELECTION) if ctx is not None else None

    async def _remember_selection(self, identity: ClientIdentity | None) -> None:
        ctx = self._session_context
        if ctx is not None and identity is not None:
            await ctx.set_state(_SELECTION, identity.repo)

    @staticmethod
    def _checkout(path: object) -> Checkout | None:
        return Checkout.find(Path(path)) if isinstance(path, str) else None
