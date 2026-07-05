"""Unit tests for WidgetSync — the patch-to-WidgetState mirror.

Drive :class:`WidgetSync` directly: a value-bearing input writes its post-patch
value into :class:`WidgetState`, a kind excluded from the value dispatch has its
cache discarded, and a moved window is marked in the shared dirty-windows set.
"""

from __future__ import annotations

from punt_lux.protocol import (
    ColorPickerElement,
    InputNumberElement,
    TextElement,
    WindowElement,
)
from punt_lux.scene.widget_state import WidgetState
from punt_lux.scene.widget_sync import WidgetSync


def _make_sync() -> tuple[WidgetSync, set[str]]:
    """Build a WidgetSync over a fresh dirty-windows set."""
    dirty: set[str] = set()
    return WidgetSync(dirty_windows=dirty), dirty


def test_value_patch_mirrors_into_widget_state() -> None:
    """A value-bearing input writes its post-patch value into WidgetState."""
    sync, _ = _make_sync()
    ws = WidgetState()

    sync.sync(InputNumberElement(id="in1", label="N", value=42.0), {"value": 42.0}, ws)

    assert ws.get("in1") == 42.0


def test_value_patch_on_color_picker_discards_widget_state() -> None:
    """A kind excluded from the value dispatch has its cache discarded."""
    sync, _ = _make_sync()
    ws = WidgetState()
    ws.set("cp1", (0.0, 1.0, 0.0, 1.0))

    sync.sync(
        ColorPickerElement(id="cp1", label="Tint", value="#00FF00"), {"value": "x"}, ws
    )

    sentinel = object()
    assert ws.get("cp1", sentinel) is sentinel


def test_position_patch_marks_window_dirty() -> None:
    """A moved window is added to the shared dirty-windows set."""
    sync, dirty = _make_sync()

    sync.sync(
        WindowElement(id="w1", title="Panel", children=[]), {"x": 10, "y": 20}, ws=None
    )

    assert "w1" in dirty


def test_non_value_patch_leaves_widget_state_untouched() -> None:
    """A patch with no value/position keys touches neither cache nor dirty set."""
    sync, dirty = _make_sync()
    ws = WidgetState()

    sync.sync(TextElement(id="t1", content="Hello"), {"content": "New"}, ws)

    sentinel = object()
    assert ws.get("t1", sentinel) is sentinel
    assert not dirty
