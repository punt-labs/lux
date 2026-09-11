"""Regression guard: the ``domain.hub`` package import cycle stays broken.

PR #466's Tarjan SCC fix made a pre-existing 7-member import cycle fully
visible: ``domain.hub`` (``__init__``), ``client_roster``, ``clients``,
``hub_clients``, ``hub_display``, ``lifecycle``, and ``menu_group_key``. The
cycle closed with ``menu_group_key.py`` importing its own package
(``from punt_lux.domain.hub import applet_name_format``) rather than the
submodule it actually needed
(``from punt_lux.domain.hub.applet_name_format import session_pid_from_name``).
This test scores the real source tree with ``CouplingScorer`` -- the same
computation ``make check-coupling`` runs -- so a future change that
reintroduces the package-level self-import fails loud here instead of
silently regrowing the cycle.
"""

from __future__ import annotations

from pathlib import Path

from tools.oo_coupling import CouplingScorer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "punt_lux"

_FORMER_CYCLE_MEMBERS = frozenset(
    {
        "domain.hub",
        "domain.hub.client_roster",
        "domain.hub.clients",
        "domain.hub.hub_clients",
        "domain.hub.hub_display",
        "domain.hub.lifecycle",
        "domain.hub.menu_group_key",
    }
)


class TestDomainHubCycleStaysBroken:
    """The 7-member ``domain.hub`` SCC (lux-2bbg) must never reappear."""

    def test_no_former_member_is_in_a_cycle(self) -> None:
        pkg_modules = CouplingScorer._discover_package_modules(_SRC)
        scorer = object.__new__(CouplingScorer)
        graph = CouplingScorer._build_import_graph(scorer, _SRC, pkg_modules)
        cycle_members = CouplingScorer._find_cycle_members(graph)

        assert cycle_members.isdisjoint(_FORMER_CYCLE_MEMBERS)
