"""RaisingRendererFactory satisfies RendererFactory and fails loud on call.

The Hub-tier sentinel factory must refuse to produce a renderer — any
``elem.render()`` reached outside the display tier raises ``RuntimeError``
naming the offending element, so a tier-routing bug surfaces immediately.
"""

from __future__ import annotations

import pytest

from punt_lux.protocol.renderers import RaisingRendererFactory


def test_raising_renderer_factory_raises_runtime_error_on_call() -> None:
    factory = RaisingRendererFactory()
    with pytest.raises(RuntimeError, match="cannot be rendered on this tier"):
        factory(object())


def test_raising_renderer_factory_names_element_type_in_message() -> None:
    class _Sample:
        pass

    factory = RaisingRendererFactory()
    with pytest.raises(RuntimeError, match="_Sample"):
        factory(_Sample())
