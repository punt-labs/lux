"""Discover the local Git checkouts advertised by an MCP client."""

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

_ROOTS = "lux:repo-roots"


@dataclass(frozen=True, slots=True)
class RepoRoots:
    context: Context | None

    async def advertised(self) -> tuple[Checkout, ...]:
        ctx = self.context
        if ctx is None or ctx.request_context is None:
            return ()
        remembered: list[object] | None = await ctx.get_state(_ROOTS)
        if remembered is not None:
            return self._from_cache(remembered)
        caps = ctx.session.client_capabilities
        if caps is None or caps.roots is None:
            return ()
        roots = await self._discover(ctx)
        await ctx.set_state(_ROOTS, [str(checkout.root) for checkout in roots])
        return roots

    @staticmethod
    def _from_cache(paths: list[object]) -> tuple[Checkout, ...]:
        return tuple(Checkout(Path(path)) for path in paths if isinstance(path, str))

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

    @staticmethod
    def _local_root(uri: str) -> Checkout | None:
        url = urlsplit(uri)
        if url.scheme == "file" and url.netloc in {"", "localhost"}:
            return Checkout.find(Path(unquote(url.path)))
        return None
