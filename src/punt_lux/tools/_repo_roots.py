"""Resolve and gate the advertised and declared checkouts for a session."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

import anyio
import mcp_types as mt
from mcp.shared.exceptions import MCPError

from punt_lux.service.repo_activation import Checkout

if TYPE_CHECKING:
    from fastmcp import Context

    from punt_lux.service.repo_activation import ActivationState

_ROOTS = "lux:repo-roots"


@dataclass(frozen=True, slots=True)
class RepoRoots:
    context: Context | None

    async def off_state(
        self, declared: object, identified: str | None
    ) -> ActivationState | None:
        target = self._checkout(declared) or self._checkout(identified)
        roots = await self._advertised()
        root = roots[0] if roots and target not in roots else None
        for checkout in (root, target):
            if checkout is not None and not (state := checkout.state()).enabled:
                return state
        return None

    @staticmethod
    def _checkout(path: object) -> Checkout | None:
        return Checkout.find(Path(path)) if isinstance(path, str) else None

    async def _advertised(self) -> tuple[Checkout, ...]:
        ctx = self.context
        if ctx is None or ctx.request_context is None:
            return ()
        remembered: list[object] | None = await ctx.get_state(_ROOTS)
        if remembered is not None:
            return tuple(
                Checkout(Path(item)) for item in remembered if isinstance(item, str)
            )
        caps = ctx.session.client_capabilities
        if caps is None or caps.roots is None:
            return ()
        roots = await self._discover(ctx)
        await ctx.set_state(_ROOTS, [str(checkout.root) for checkout in roots])
        return roots

    @classmethod
    async def _discover(cls, ctx: Context) -> tuple[Checkout, ...]:
        with anyio.move_on_after(1):
            try:
                results = await ctx.session.send_request(
                    mt.ListRootsRequest(), mt.ListRootsResult
                )
            except MCPError:
                return ()
            return tuple(
                checkout
                for root in results.roots
                if (checkout := cls._local_root(str(root.uri))) is not None
            )
        return ()

    @classmethod
    def _local_root(cls, uri: str) -> Checkout | None:
        url = urlsplit(uri)
        if url.scheme == "file" and url.netloc in {"", "localhost"}:
            return cls._checkout(unquote(url.path))
        return None
