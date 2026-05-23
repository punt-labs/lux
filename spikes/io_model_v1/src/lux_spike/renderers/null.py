"""NullRendererFactory — used on Hub and Agent tiers.

Per io-model.md: "Hub tier: the Decoder constructing inbound Elements
injects NullRendererFactory. The hub never iterates its scene for
drawing; the injected factory is dead weight but keeps the constructor
signature uniform across tiers."
"""

from __future__ import annotations


class NullRenderer:
    def render(self) -> None:
        pass

    def begin(self) -> None:
        pass

    def end(self) -> None:
        pass


_NULL = NullRenderer()


class NullRendererFactory:
    def __call__(self, elem: object) -> NullRenderer:
        return _NULL
