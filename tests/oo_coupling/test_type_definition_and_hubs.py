"""The BaseModel LCOM exemption and the wiring-hub relaxed efferent tier.

Two tool-correctness rules the coupling ratchet grew for the agent-menu
dispatch work (DES-095 escalate-per-file, leader-ruled 2026-09-12):

1. A pydantic ``BaseModel`` is a data-shape class whose cohesion lives in its
   public fields, which the ``self._*`` LCOM heuristic cannot see -- so it is
   skipped for LCOM exactly as ``Protocol``/``TypedDict`` already are. A plain
   class with disjoint private state still scores a real LCOM.
2. Wiring-hub modules (the Operations facade, the composition root, the thin
   MCP tool adapter) aggregate the engine by design and get a relaxed efferent
   cap, as ``__main__.py`` does; every other module keeps the default.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from tools.oo_coupling import CouplingScorer

_HEADER = "from __future__ import annotations\n\n\n"

_BASEMODEL_SRC = (
    "from __future__ import annotations\n\n"
    "from pydantic import BaseModel\n\n\n"
    "class Widget(BaseModel):\n"
    "    label: str\n"
    "    tone: str\n\n"
    "    def render(self) -> str:\n"
    "        return self.label\n\n"
    "    def shout(self) -> str:\n"
    "        return self.tone.upper()\n"
)

# A plain class whose two methods touch disjoint private state -- a genuine
# lack of cohesion the heuristic must still report (LCOM 1.0), proving the
# BaseModel skip is targeted, not a blanket disabling of LCOM.
_PLAIN_SRC = (
    f"{_HEADER}"
    "class Store:\n"
    "    def __new__(cls) -> Store:\n"
    "        self = super().__new__(cls)\n"
    "        self._a = 1\n"
    "        self._b = 2\n"
    "        return self\n\n"
    "    def use_a(self) -> int:\n"
    "        return self._a\n\n"
    "    def use_b(self) -> int:\n"
    "        return self._b\n"
)


def _max_lcom(scorer: CouplingScorer, stem: str) -> float:
    for result in scorer.results:
        if str(result["file"]).endswith(f"{stem}.py"):
            return cast("float", result["max_lcom"])
    raise AssertionError(f"no scored result for {stem}.py")


def test_basemodel_is_exempt_from_lcom_but_a_plain_class_is_not(
    tmp_path: Path,
) -> None:
    (tmp_path / "widget.py").write_text(_BASEMODEL_SRC)
    (tmp_path / "store.py").write_text(_PLAIN_SRC)

    scorer = CouplingScorer(tmp_path)

    # The BaseModel's two public-field methods would read as zero-cohesion
    # (LCOM 1.0) under the private-attr heuristic; the skip records 0.0.
    assert _max_lcom(scorer, "widget") == 0.0
    # The plain class's disjoint private state is a real LCOM the skip leaves
    # measured (its ``use_a``/``use_b`` pair shares nothing), proving the skip
    # is targeted at data-shape classes, not a blanket disabling of LCOM.
    assert _max_lcom(scorer, "store") > 0.0


def test_wiring_hub_efferent_cap_is_relaxed_only_for_the_named_roles() -> None:
    default = CouplingScorer._relaxed_thresholds("src/punt_lux/operations/other.py")
    assert default["efferent_coupling"] == ("<=", 7.0)

    # The three exact repository-relative members get the relaxed cap, whether
    # the scored path arrives relative or absolute.
    for member in CouplingScorer.WIRING_HUB_PATHS:
        assert CouplingScorer._relaxed_thresholds(member)["efferent_coupling"] == (
            "<=",
            20.0,
        )
        absolute = f"/home/dev/lux/{member}"
        assert CouplingScorer._relaxed_thresholds(absolute)["efferent_coupling"] == (
            "<=",
            20.0,
        )

    main = CouplingScorer._relaxed_thresholds("pkg/__main__.py")
    assert main["efferent_coupling"] == ("<=", 15.0)
    assert main["public_names"] == ("<=", 100.0)


def test_wiring_hub_cap_is_not_granted_to_a_same_suffix_path_outside_the_package() -> (
    None
):
    # The bug the exact-path match closes: an endswith match relaxed any path
    # ending "operations/facade.py". A different package (or a fixture/vendor
    # tree) with the same suffix must get the DEFAULT cap, not the wiring-hub
    # tier — only the canonical src/punt_lux/... path is a member.
    impostor = CouplingScorer._relaxed_thresholds("pkg/other/operations/facade.py")
    assert impostor["efferent_coupling"] == ("<=", 7.0)

    real = CouplingScorer._relaxed_thresholds("src/punt_lux/operations/facade.py")
    assert real["efferent_coupling"] == ("<=", 20.0)


def test_wiring_hub_cap_survives_a_checkout_parent_that_repeats_the_anchor() -> None:
    # The bug the last-occurrence slice closes: canonicalization slices from the
    # package anchor "src/punt_lux/". In the common ~/src/punt_lux/... dev
    # layout the checkout directory itself repeats the segment, so it appears
    # twice. Slicing from the FIRST occurrence yields a path outside
    # WIRING_HUB_PATHS and silently withholds the relaxed cap; slicing from the
    # LAST occurrence recovers the real package root.
    double_anchor = "/home/u/src/punt_lux/checkout/src/punt_lux/operations/facade.py"
    assert CouplingScorer._relaxed_thresholds(double_anchor)["efferent_coupling"] == (
        "<=",
        20.0,
    )

    # A non-member module under the same doubled-anchor layout still gets the
    # default cap — the last-occurrence slice canonicalizes, it does not relax.
    non_member = "/home/u/src/punt_lux/checkout/src/punt_lux/operations/other.py"
    assert CouplingScorer._relaxed_thresholds(non_member)["efferent_coupling"] == (
        "<=",
        7.0,
    )
