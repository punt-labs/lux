"""JsonElementFactory — top-level wire decoder dispatching by ``kind``.

Per docs/oo-refactor/pr3-v2.1-design.md §1 row 4 and §3: the io-model
inbound dispatcher. One instance per tier (constructed at startup with
that tier's ``RendererFactory`` + ``Emit``); each ``decode(raw)`` call
routes to the per-kind decoder for ``raw["kind"]``.

PR 3 ships Text-only dispatch. PRs 4-11 add Button, Panel, Dialog, and
the remaining 19 kinds as each family migrates from the PR-2
``ElementCodec`` path to the io-model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonElementFactory"]


class JsonElementFactory:
    """Dispatch wire dicts to per-kind decoders by their ``kind`` field.

    Holds the tier's ``RendererFactory`` + ``Emit`` so every decoded
    element is born with the same injected DI. A missing, empty, or
    non-string ``kind`` is the dispatcher's responsibility — this factory
    trusts that the caller has already validated the ``kind`` discriminator
    (the validation lives in ``protocol/elements/__init__.element_from_dict``
    so all 24 element kinds share one boundary check).
    """

    _rf: RendererFactory
    _emit: Emit

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        return self

    def decode(self, raw: Mapping[str, object]) -> TextElement:
        """Dispatch by ``raw["kind"]`` to the per-kind decoder.

        PR 3 only handles ``"text"``. PR 4 adds ``"button"``, ``"panel"``,
        ``"dialog"`` cases here; the dispatcher in
        ``protocol/elements/__init__.element_from_dict`` already routes
        only matching kinds to this factory, so unknown-kind raising
        lives at the higher layer.
        """
        kind = raw.get("kind")
        if kind == "text":
            return JsonTextDecoder(
                renderer_factory=self._rf,
                emit=self._emit,
                element_cls=TextElement,
            ).decode(raw)
        msg = f"JsonElementFactory has no decoder for kind={kind!r}"
        raise ValueError(msg)
