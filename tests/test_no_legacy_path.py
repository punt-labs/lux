"""Keep one authoritative Hub write path and one Element ABC rendering model."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import punt_lux.protocol as protocol
import punt_lux.protocol.elements as elements

# Guard the obsolete module paths, not the replica that owns placement.
_DELETED_MODULES = (
    "punt_lux.protocol.elements.layout",
    "punt_lux.protocol.elements.legacy_table",
    "punt_lux.protocol.elements.container_abc_gate",
    "punt_lux.protocol.elements.codec",
    "punt_lux.display.element_renderer",
    "punt_lux.display.table_renderer",
    "punt_lux.display.renderers.container_renderer",
    "punt_lux.display.renderers.modal_renderer",
    "punt_lux.display.domain_pump",
    "punt_lux.scene",
    "punt_lux.scene.manager",
)

# Source patterns that only the legacy path produces. A grep over ``src`` for
# these must return nothing outside git history.
_FORBIDDEN_SOURCE_PATTERNS = (
    # The six deleted Legacy*Element classes, named precisely rather than by
    # the bare "class Legacy" prefix -- "legacy" is also the correct English
    # word for the unrelated service-lifecycle domain (LegacySweep and kin,
    # src/punt_lux/_legacy_sweep.py: curing pre-rename launchd/systemd
    # registrations), and a bare-prefix match would forbid that legitimate
    # reuse along with the real element-migration regression it exists to
    # catch.
    "class LegacyTableElement",
    "class LegacyGroupElement",
    "class LegacyTabBarElement",
    "class LegacyCollapsingHeaderElement",
    "class LegacyWindowElement",
    "class LegacyModalElement",
    "ContainerAbcGate",  # the all-ABC fork gate
    "class ElementCodec",  # the legacy dispatch table
    "build_element_codec",  # the legacy-codec factory
    "_decode_legacy",  # the factory's legacy decode arm
    "NestedLegacyWriteError",  # the legacy nested-write deferral
    "LegacyFieldRealization",  # the legacy replace-and-rebind write
    "class DomainPump",  # the deleted dual-write mirror
    "class SceneManager",  # the pre-rename name; SceneReplica is current
)

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "punt_lux"


def test_no_legacy_names_are_exported() -> None:
    """Neither protocol surface exports a name containing ``Legacy``."""
    leaked = [
        name
        for module in (protocol, elements)
        for name in getattr(module, "__all__", ())
        if "Legacy" in name
    ]
    assert leaked == [], f"legacy names re-exported: {leaked}"


def test_element_union_has_no_legacy_member() -> None:
    """The ``Element`` union names no ``Legacy*`` member."""
    from typing import get_args

    offenders = [
        cls.__name__
        for cls in get_args(elements.Element)
        if "Legacy" in getattr(cls, "__name__", "")
    ]
    assert offenders == [], f"legacy members in the Element union: {offenders}"


@pytest.mark.parametrize("module", _DELETED_MODULES)
def test_deleted_module_stays_deleted(module: str) -> None:
    """Importing a deleted legacy module raises ``ModuleNotFoundError``."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_no_forbidden_legacy_pattern_in_source() -> None:
    """No source file reintroduces a legacy-only symbol.

    This test's own literals are excluded — it names the patterns to forbid
    them, and is not under ``src``.
    """
    hits: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(_SRC_ROOT)
        hits.extend(
            f"{rel}: {pattern!r}"
            for pattern in _FORBIDDEN_SOURCE_PATTERNS
            if pattern in text
        )
    assert hits == [], "legacy machinery reappeared in src:\n" + "\n".join(hits)
