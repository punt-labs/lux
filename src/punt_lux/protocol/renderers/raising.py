"""RaisingRendererFactory — fail-loud sentinel for non-display tiers.

The Hub and Agent tiers never paint, yet every Element carries a
``RendererFactory`` so the construction signature stays uniform across
tiers. A factory that returns a no-op renderer (the discarded Null
Object) silently swallowed ``elem.render()`` calls made from the wrong
tier, hiding the bug. This factory raises ``RuntimeError`` on call,
turning any accidental render-outside-the-display-tier into a loud
failure instead of an invisible paint.

The display tier sidesteps this factory at decode time by injecting its
own ``_imgui_renderer_factory``; the Hub/Agent tiers, and the sentinel
defaults on direct ``TextElement(...)`` construction, get this factory.
"""

from __future__ import annotations

from typing import NoReturn, Self

__all__ = ["RaisingRendererFactory"]


class RaisingRendererFactory:
    """RendererFactory that refuses to produce renderers.

    Carries no state. The single ``__call__`` raises ``RuntimeError``
    naming the offending element so a misrouted render is immediately
    traceable to its source. ``NoReturn`` is structurally compatible
    with the ``Renderer`` return type the ``RendererFactory`` Protocol
    expects.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, elem: object) -> NoReturn:
        """Raise — this tier must not invoke ``elem.render()``."""
        msg = (
            "RaisingRendererFactory.__call__: element "
            f"{type(elem).__name__} cannot be rendered on this tier; "
            "inject a display-tier RendererFactory at decode time."
        )
        raise RuntimeError(msg)
