"""Tests for the shared Element-ABC construction DI sentinels.

``NO_EMIT`` and ``RAISING_FACTORY`` replace the ``_no_emit`` function and
per-file ``RaisingRendererFactory()`` instance that were duplicated in
text.py, button.py, checkbox.py, and dialog.py. The four exemplars now
default to these shared sentinels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.protocol.elements.abc_di_defaults import (
    NO_EMIT,
    RAISING_FACTORY,
    NoEmit,
)
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory


def test_no_emit_is_a_callable_null_object() -> None:
    """The shared sentinel is callable and swallows the message silently."""
    NO_EMIT("anything")  # must not raise — the Hub tier has no emit sink


def test_no_emit_class_constructs_a_fresh_null_object() -> None:
    NoEmit()("msg")  # must not raise


def test_raising_factory_fails_loud_on_render() -> None:
    """A non-display tier must not paint — the sentinel raises, never no-ops."""
    with pytest.raises(RuntimeError, match=r"cannot be rendered on this tier"):
        RAISING_FACTORY(object())


def test_real_factory_resolves_a_renderer_after_rebind(
    real_imgui_factory: ImGuiRendererFactory,
) -> None:
    """The positive complement: the real factory resolves where the sentinel raises.

    ``render()`` resolves its renderer at exactly the call the sentinel test
    above fails on: ``self._renderer_factory(self)``. With a directly-constructed
    element the factory is the fail-loud sentinel; after the Display's rebind it
    is the real ``ImGuiRendererFactory``, which returns an ``ImGuiTextRenderer``
    without raising. The subsequent ``renderer.render()`` paint hits real ImGui
    and is covered by the visual/e2e tier (it segfaults without a GL context),
    so this asserts the guarded resolution the rebind makes safe.
    """
    elem = TextElement(id="t", content="hi")
    assert isinstance(elem._renderer_factory, type(RAISING_FACTORY))

    elem.bind_renderer_factory(real_imgui_factory)

    renderer = elem._renderer_factory(elem)
    assert isinstance(renderer, ImGuiTextRenderer)


def test_exemplars_construct_with_the_shared_sentinels() -> None:
    """Direct construction of each exemplar uses the shared defaults.

    A directly-constructed element carries ``RAISING_FACTORY``, so any
    accidental ``elem.render()`` raises instead of silently painting.
    """
    from punt_lux.protocol.elements import (
        ButtonElement,
        CheckboxElement,
        DialogElement,
        TextElement,
    )

    for elem in (
        TextElement(id="t", content="hi"),
        ButtonElement(id="b", label="OK"),
        CheckboxElement(id="c", label="Bold"),
        DialogElement(id="d", title="Confirm"),
    ):
        with pytest.raises(RuntimeError, match=r"cannot be rendered on this tier"):
            elem.render()
