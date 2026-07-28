"""Beads Browser — load beads issues and install the Hub menu board."""

from __future__ import annotations

from typing import Any

from punt_lux.apps._beads_payload import BeadsLoader, BeadsPayloadBuilder


class BeadsBrowser:
    """Fetch beads issues and install the Hub menu board in-process.

    The browser is the data provider — ``load`` runs ``bd`` and ``build_payload``
    shapes its rows — plus ``render``, the in-process install the Hub menu
    triggers. Request construction lives on ``BeadsBoard``; ``render`` builds one
    and installs it through the same ``render_table`` operation the CLI and MCP
    surfaces use, so the composed chrome runs Hub-side and stays live.
    """

    def load(
        self, *, all_issues: bool = False
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch, default-fill, filter, and sort beads issues via ``bd``.

        Returns ``(issues, error)``: a sorted list and ``None`` on success, or
        ``[]`` and a short reason on any failure.
        """
        issues, err = BeadsLoader().run(all_issues=all_issues)
        if err is not None:
            return [], err

        # Three-pass stable sort: updated_at desc, priority asc, in_progress top.
        issues.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
        issues.sort(key=lambda i: i["priority"])
        issues.sort(key=lambda i: i["status"] != "in_progress")
        return issues, None

    def build_payload(self, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the table columns/rows/filters/detail payload for beads issues."""
        return BeadsPayloadBuilder().build(issues)

    def render(self) -> None:
        """Install the Hub menu beads board through the operations facade.

        Imports are local to avoid an import-time cycle: the facade lives in
        ``tools``, which imports the client registry that imports this module.
        The board lives under the Hub menu's ``beads-`` namespace, distinct from
        the CLI's ``beads-cli-`` board (a separate owner). A rejected install is
        logged and shown as a red failure scene — the menu surface must not fail
        silently where the CLI surface reports the reason.
        """
        from pathlib import Path

        from punt_lux.apps.beads_board import BeadsBoard
        from punt_lux.apps.beads_installer import BeadsBoardInstaller
        from punt_lux.domain.ids import ConnectionId
        from punt_lux.operations import Scope

        project = Path.cwd().name or "unknown"
        board = BeadsBoard(f"beads-{project}", f"Beads: {project}")
        request = board.request(self.load())
        scope = Scope(ConnectionId("app-beads"))
        BeadsBoardInstaller.install(board, request, scope)
