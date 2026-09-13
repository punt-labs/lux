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

# A stateless marker (WireSeparator's shape): __slots__ = () and methods that
# touch no self._*. The private-attr heuristic sees every method's attr-set as
# empty and reads LCOM 1.0 -- a false zero-cohesion for a class with no state.
_MARKER_SRC = (
    f"{_HEADER}"
    "class Separator:\n"
    "    __slots__ = ()\n\n"
    "    def label(self) -> str:\n"
    '        return "---"\n\n'
    "    def item_id(self) -> str:\n"
    '        return ""\n'
)

# A frozen value object: its fields are set by the generated __init__ outside
# the AST, so there is no self._* store, and its methods read public fields the
# heuristic cannot see -- the same false LCOM 1.0.
_FROZEN_SRC = (
    "from __future__ import annotations\n\n"
    "from dataclasses import dataclass\n\n\n"
    "@dataclass(frozen=True)\n"
    "class Point:\n"
    "    x: int\n"
    "    y: int\n\n"
    "    def left(self) -> int:\n"
    "        return self.x\n\n"
    "    def top(self) -> int:\n"
    "        return self.y\n"
)

# A hand-written immutable value class: it bypasses its own blocked
# __setattr__ with object.__setattr__ to establish two DISJOINT private
# fields -- real state the stateless-value skip must not hide. Unlike
# _FROZEN_SRC (whose fields never appear in the AST at all), this class's
# state IS visible to the AST, via a Call rather than a direct Attribute
# store, so the exemption must not fire.
_OBJECT_SETATTR_SRC = (
    f"{_HEADER}"
    "class Coord:\n"
    "    __slots__ = ('_x', '_y')\n\n"
    "    def __new__(cls, x: int, y: int) -> Coord:\n"
    "        self = super().__new__(cls)\n"
    '        object.__setattr__(self, "_x", x)\n'
    '        object.__setattr__(self, "_y", y)\n'
    "        return self\n\n"
    "    def use_x(self) -> int:\n"
    "        return self._x\n\n"
    "    def use_y(self) -> int:\n"
    "        return self._y\n"
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


def test_stateless_value_objects_are_exempt_but_a_stateful_class_is_not(
    tmp_path: Path,
) -> None:
    (tmp_path / "separator.py").write_text(_MARKER_SRC)
    (tmp_path / "point.py").write_text(_FROZEN_SRC)
    (tmp_path / "store.py").write_text(_PLAIN_SRC)

    scorer = CouplingScorer(tmp_path)

    # A stateless marker and a frozen value object store no ``self._*`` and would
    # read as zero-cohesion (LCOM 1.0) under the private-attr heuristic; the
    # stateless-value skip records 0.0 for each.
    assert _max_lcom(scorer, "separator") == 0.0
    assert _max_lcom(scorer, "point") == 0.0
    # A class that DOES assign disjoint private state is still measured, proving
    # the skip is targeted at stateless value objects, not any low-cohesion class.
    assert _max_lcom(scorer, "store") > 0.0


def test_object_setattr_private_state_is_not_treated_as_stateless(
    tmp_path: Path,
) -> None:
    (tmp_path / "coord.py").write_text(_OBJECT_SETATTR_SRC)

    scorer = CouplingScorer(tmp_path)

    # object.__setattr__(self, "_x", ...) is a Call, not an Attribute store, so
    # the direct-assignment scan alone would miss it and wrongly read this class
    # as stateless. Its two private fields are disjoint, so a correctly-detected
    # class scores a real LCOM rather than the false 0.0 exemption.
    assert _max_lcom(scorer, "coord") > 0.0


def test_wiring_hub_efferent_cap_is_relaxed_only_for_the_named_roles() -> None:
    default = CouplingScorer._relaxed_thresholds("src/punt_lux/operations/other.py")
    assert default["efferent_coupling"] == ("<=", 7.0)

    # The three exact repository-relative members get the relaxed cap, whether
    # the scored path arrives relative (matched verbatim) or absolute (made
    # relative to the real repository root before the exact-membership test).
    repo_root = "/home/dev/lux"
    for member in CouplingScorer.WIRING_HUB_PATHS:
        assert CouplingScorer._relaxed_thresholds(member)["efferent_coupling"] == (
            "<=",
            20.0,
        )
        absolute = f"{repo_root}/{member}"
        assert CouplingScorer._relaxed_thresholds(absolute, repo_root)[
            "efferent_coupling"
        ] == ("<=", 20.0)

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
    # A checkout whose parent directory itself contains a "src/punt_lux"
    # segment (the ~/src/punt_lux/... dev layout) makes the anchor appear twice
    # in the absolute path. Making the path relative to the REAL repository
    # root recovers the package-relative form regardless — no substring search
    # over a segment that appears more than once.
    repo_root = "/home/u/src/punt_lux/checkout"
    double_anchor = f"{repo_root}/src/punt_lux/operations/facade.py"
    assert CouplingScorer._relaxed_thresholds(double_anchor, repo_root)[
        "efferent_coupling"
    ] == ("<=", 20.0)

    # A non-member module under the same doubled-anchor layout still gets the
    # default cap — the repo-relative form is exact-matched, not relaxed.
    non_member = f"{repo_root}/src/punt_lux/operations/other.py"
    assert CouplingScorer._relaxed_thresholds(non_member, repo_root)[
        "efferent_coupling"
    ] == ("<=", 7.0)


def test_wiring_hub_cap_is_denied_to_a_tree_outside_the_real_repo_root() -> None:
    # The definitive boundary: a vendored/fixture/temp tree that merely
    # CONTAINS a "src/punt_lux/..." segment must NOT receive the wiring-hub cap
    # just because the suffix matches an allowlist entry. Anchored to the real
    # repository root, such a path has no repository-relative form under the
    # root, so it falls to the default cap. A substring match (index/rindex)
    # would wrongly relax it to 20.
    repo_root = "/home/u/src/punt_lux/checkout"
    vendored = "/tmp/vendor/src/punt_lux/operations/facade.py"
    assert CouplingScorer._relaxed_thresholds(vendored, repo_root)[
        "efferent_coupling"
    ] == ("<=", 7.0)
