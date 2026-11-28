"""Resolve which advertised or declared checkout gates a tool call."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self

from punt_lux.service.repo_activation import Checkout
from punt_lux.tools._repo_roots import RepoRoots

if TYPE_CHECKING:
    from fastmcp import Context

    from punt_lux.service.repo_activation import ActivationState


class RepoSelection:
    _context: Context | None
    __slots__ = ("_context",)

    def __new__(cls, context: Context | None) -> Self:
        self = super().__new__(cls)
        self._context = context
        return self

    async def off_state(
        self, declared: object, selected: object
    ) -> ActivationState | None:
        target = self._checkout(declared) or self._checkout(selected)
        roots = await RepoRoots(self._context).advertised()
        root = roots[0] if roots and target not in roots else None
        for checkout in (root, target):
            if checkout is not None and not (state := checkout.state()).enabled:
                return state
        return None

    @staticmethod
    def _checkout(path: object) -> Checkout | None:
        return Checkout.find(Path(path)) if isinstance(path, str) else None
