"""MCP front door for repository integration and status."""

from __future__ import annotations

from pathlib import Path

from punt_lux.service.display_mode_store import DisplayModeStore
from punt_lux.service.enablement import Action, Enablement
from punt_lux.service.repo_activation import Checkout, Scope
from punt_lux.tools.repo_gate import RepoGate
from punt_lux.tools.server import mcp as mcp
from punt_lux.wire.operations import OpError

mcp.add_middleware(RepoGate())


class _RepoTools:
    @staticmethod
    def enablement(
        repo: str,
        action: Action,
        scope: Scope = "local",
        *,
        refresh: bool = False,
        opt_out: bool = False,
        clear_opt_out: bool = False,
    ) -> str:
        """Explicitly enable or disable Lux integration in your absolute repo path."""
        try:
            checkout = _RepoTools._checkout(repo)
            if (refresh or clear_opt_out) and action != "enable":
                return "error: refresh and clear_opt_out require enable"
            if opt_out and action != "disable":
                return "error: opt_out requires disable"
            result = Enablement(checkout, scope).apply(
                action, refresh=refresh, opt_out=opt_out, clear_opt_out=clear_opt_out
            )
        except (OSError, ValueError) as exc:
            return f"error: {exc}"
        return result.describe()

    @staticmethod
    def status(repo: str) -> str:
        """Report what decides Lux integration, and the personal display preference."""
        try:
            checkout = _RepoTools._checkout(repo)
        except ValueError as exc:
            return f"error: {exc}"
        mode = DisplayModeStore(repo).read()
        line = checkout.state().describe()
        if isinstance(mode, OpError):
            return f"{line}\nDisplay preference unavailable: {mode.reason}"
        return f"{line}\nLux display preference: {mode.mode}"

    @staticmethod
    def _checkout(repo: str) -> Checkout:
        path = Path(repo)
        if not path.is_absolute():
            msg = "repo must be an absolute path"
            raise ValueError(msg)
        return Checkout.resolve(path)


enablement = mcp.tool(_RepoTools.enablement)
status = mcp.tool(_RepoTools.status)
