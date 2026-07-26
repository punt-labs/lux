"""A legacy window records its geometry; pure containers record nothing.

A legacy-decoded window is window-like — reachable under the fork when it holds a
not-yet-migrated child — so it records its rect and stack index through
``record_window`` while open, matching the ABC window adapter. A group is a pure
container: it opens no window of its own, so it records nothing (its children
record as they recurse). The ImGui backend is faked at the module boundary so the
recording wiring is provable GL-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.renderers import container_renderer
from punt_lux.display.renderers.container_renderer import ContainerRenderer
from punt_lux.protocol.elements.layout import LegacyGroupElement, LegacyWindowElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest


def _renderer(record: list[tuple[str, str]]) -> ContainerRenderer:
    return ContainerRenderer(
        WidgetState(),
        lambda _win_id: False,
        lambda _child: None,
        lambda i, k: record.append((i, k)),
    )


def test_expanded_legacy_window_records_its_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    imgui.begin.return_value = (True, None)  # expanded
    monkeypatch.setattr(container_renderer, "imgui", imgui)
    record: list[tuple[str, str]] = []

    _renderer(record).render_window(LegacyWindowElement(id="w", children=[]))

    assert record == [("w", "window")]
    imgui.end.assert_called_once()


def test_collapsed_legacy_window_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    imgui.begin.return_value = (False, None)  # collapsed: no contents, no record
    monkeypatch.setattr(container_renderer, "imgui", imgui)
    record: list[tuple[str, str]] = []

    _renderer(record).render_window(LegacyWindowElement(id="w", children=[]))

    assert record == []


def test_legacy_group_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    # A pure container opens no window of its own — it records nothing, matching
    # how the ABC side skips group/tab_bar/collapsing_header.
    imgui = MagicMock()
    monkeypatch.setattr(container_renderer, "imgui", imgui)
    record: list[tuple[str, str]] = []

    _renderer(record).render_group(LegacyGroupElement(id="g", children=[]))

    assert record == []


def test_legacy_window_records_after_children_before_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The children lay out first (they can grow an auto-sized window), then the
    # settled rect is recorded, then the window closes — recording before the
    # children would capture the pre-layout size.
    order: list[str] = []
    imgui = MagicMock()
    imgui.begin.return_value = (True, None)
    imgui.end.side_effect = lambda: order.append("end")
    monkeypatch.setattr(container_renderer, "imgui", imgui)
    renderer = ContainerRenderer(
        WidgetState(),
        lambda _win_id: False,
        lambda _child: order.append("child"),
        lambda _i, _k: order.append("record"),
    )

    renderer.render_window(
        LegacyWindowElement(id="w", children=[TextElement(id="t", content="hi")])
    )

    assert order == ["child", "record", "end"]
