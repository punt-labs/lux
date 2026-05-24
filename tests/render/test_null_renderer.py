"""NullRenderer + NullRendererFactory satisfy the Renderer / Factory Protocols.

Per design doc §1 row 6: the Null renderer is the Hub-tier dead-weight
factory. Every method is a no-op; the factory returns the singleton
NullRenderer for any element.
"""

from __future__ import annotations

from punt_lux.protocol.renderers import NullRenderer, NullRendererFactory


def test_null_renderer_render_is_no_op() -> None:
    renderer = NullRenderer()
    renderer.render()


def test_null_renderer_begin_is_no_op() -> None:
    renderer = NullRenderer()
    renderer.begin()


def test_null_renderer_end_is_no_op() -> None:
    renderer = NullRenderer()
    renderer.end()


def test_null_renderer_factory_returns_null_renderer() -> None:
    factory = NullRendererFactory()
    result = factory(object())
    assert isinstance(result, NullRenderer)


def test_null_renderer_factory_returns_shared_instance() -> None:
    factory = NullRendererFactory()
    first = factory(object())
    second = factory(object())
    assert first is second
