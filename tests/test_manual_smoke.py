"""Tests for ``scripts/manual_smoke.py``.

The script is a visual-verification driver, but its element-tree walker
and coverage-sanity check are pure data and must hold their contract
under refactoring.  These tests pin both.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from punt_lux.protocol.elements import (
    ButtonElement,
    CollapsingHeaderElement,
    GroupElement,
    ModalElement,
    SeparatorElement,
    Tab,
    TabBarElement,
    TextElement,
    TreeElement,
    WindowElement,
)
from punt_lux.protocol.elements.tree_node import TreeNode


@pytest.fixture(scope="module")
def manual_smoke() -> ModuleType:
    """Load ``scripts/manual_smoke.py`` as a module.

    ``scripts/`` isn't on ``sys.path`` by default; load explicitly so the
    test stays independent of how the script is invoked at runtime.
    """
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "manual_smoke.py"
    spec = importlib.util.spec_from_file_location("manual_smoke", script_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load spec for {script_path}"
        raise RuntimeError(msg)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass machinery in 3.14 can find the module
    # by __module__ name during class creation.
    sys.modules["manual_smoke"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop("manual_smoke", None)
        raise
    return mod


def test_collect_kinds_recurses_into_containers(manual_smoke: ModuleType) -> None:
    """Group/CollapsingHeader/Window/Modal children must be walked."""
    inner = (
        TextElement(id="inner-text", content="x"),
        SeparatorElement(id="inner-sep"),
    )
    group = GroupElement(id="g", layout="rows", children=inner)
    header = CollapsingHeaderElement(id="h", label="H", children=inner)
    window = WindowElement(id="w", children=inner)
    # A modal installs its body via the decoder seam, not the constructor.
    modal = ModalElement.from_dict(
        {
            "kind": "modal",
            "id": "m",
            "children": [
                {"kind": "text", "id": "m-text", "content": "x"},
                {"kind": "separator", "id": "m-sep"},
            ],
        }
    )
    kinds = manual_smoke._collect_kinds([group, header, window, modal])
    assert kinds == frozenset(
        {"group", "collapsing_header", "window", "modal", "text", "separator"}
    )


def test_collect_kinds_recurses_into_tabs(manual_smoke: ModuleType) -> None:
    """A tab_bar's every-tab children must be walked."""
    tabbar = TabBarElement(
        id="t",
        tabs=(
            Tab(tab_id="a", label="a", children=(ButtonElement(id="b", label="x"),)),
            Tab(tab_id="b", label="b", children=(SeparatorElement(id="s"),)),
        ),
        active_tab="a",
    )
    kinds = manual_smoke._collect_kinds([tabbar])
    assert kinds == frozenset({"tab_bar", "button", "separator"})


def test_collect_kinds_recurses_into_tree_nodes(manual_smoke: ModuleType) -> None:
    """TreeElement.nodes are typed values and carry no element kinds themselves."""
    tree = TreeElement(
        id="t",
        nodes=(TreeNode(label="branch", children=(TreeNode(label="leaf"),)),),
    )
    kinds = manual_smoke._collect_kinds([tree])
    # Tree contributes only "tree" — node labels are not element kinds.
    assert kinds == frozenset({"tree"})


def test_expected_kinds_matches_built_frames(manual_smoke: ModuleType) -> None:
    """The 24-kind expected set must equal the union of every frame's kinds."""
    image_path = manual_smoke._write_sample_png()
    runner = manual_smoke.SmokeRunner(image_path)
    actual = frozenset().union(
        *(manual_smoke._collect_kinds(f.elements) for f in runner.frames)
    )
    assert actual == manual_smoke._EXPECTED_KINDS


def test_runresult_exit_code_or_semantics(manual_smoke: ModuleType) -> None:
    """exit_code is a 2-bit OR: 1 for ack-None, 2 for transport-error."""
    empty = manual_smoke.RunResult()
    timeouts_only = manual_smoke.RunResult(missed_acks=["a"])
    transport_only = manual_smoke.RunResult(transport_errors=[("b", "msg")])
    both = manual_smoke.RunResult(missed_acks=["a"], transport_errors=[("b", "msg")])
    assert empty.exit_code == 0
    assert timeouts_only.exit_code == 1
    assert transport_only.exit_code == 2
    assert both.exit_code == 3


def test_runresult_is_frozen(manual_smoke: ModuleType) -> None:
    """RunResult is frozen — attribute assignment raises."""
    from dataclasses import FrozenInstanceError

    r = manual_smoke.RunResult()
    with pytest.raises(FrozenInstanceError):
        r.missed_acks = ["x"]
