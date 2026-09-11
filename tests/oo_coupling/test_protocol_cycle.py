"""Regression guard: the ``protocol`` package import cycle stays broken.

PR #466's Tarjan SCC fix made a pre-existing 5-member import cycle fully
visible: ``protocol`` (``__init__``), ``protocol.elements``,
``protocol.messages``, ``protocol.messages.scene``, and
``protocol.messages.scene_codec``. The cycle closed with
``protocol/elements/__init__.py`` importing its own package
(``from punt_lux.protocol.elements import container_dispatch``) rather than
the submodule it actually needed
(``from punt_lux.protocol.elements.container_dispatch import dispatch``) --
the same self-import-via-parent-package shape every other consumer of
``container_dispatch`` already avoided. This test scores the real source
tree with ``CouplingScorer`` -- the same computation ``make check-coupling``
runs -- so a future change that reintroduces the package-level self-import
fails loud here instead of silently regrowing the cycle.
"""

from __future__ import annotations

from pathlib import Path

from tools.oo_coupling import CouplingScorer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "punt_lux"

_FORMER_CYCLE_MEMBERS = frozenset(
    {
        "protocol",
        "protocol.elements",
        "protocol.messages",
        "protocol.messages.scene",
        "protocol.messages.scene_codec",
    }
)


class TestProtocolCycleStaysBroken:
    """The 5-member ``protocol`` SCC (lux-2bbg) must never reappear."""

    def test_no_former_member_is_in_a_cycle(self) -> None:
        pkg_modules = CouplingScorer._discover_package_modules(_SRC)
        scorer = object.__new__(CouplingScorer)
        graph = CouplingScorer._build_import_graph(scorer, _SRC, pkg_modules)
        cycle_members = CouplingScorer._find_cycle_members(graph)

        assert cycle_members.isdisjoint(_FORMER_CYCLE_MEMBERS)
