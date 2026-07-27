"""JsonPlotDecoder + JsonPlotEncoder — wire codec for ``PlotElement``.

The codec body lives in this sibling module rather than on ``PlotElement``.
``PlotElement.to_dict`` / ``PlotElement.from_dict`` remain as short delegators so
the runtime-checkable ``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at construction;
off the display tier that is the fail-loud sentinel, which the Display rebinds
post-receive. Series decode through ``PlotSeries.decode_all``, so a non-string
label or non-numeric coordinate raises ``ValueError`` at the boundary — the
crash payload never reaches the display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.plot_series import PlotSeries

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.plot import PlotElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonPlotDecoder", "JsonPlotEncoder"]


class JsonPlotDecoder:
    """Decode a wire dict to a fully-constructed ``PlotElement``.

    Constructed once per tier with that tier's ``renderer_factory`` + ``emit``;
    every decoded element is born with the same injected DI. Boundary validation
    (PY-EH-1) routes through ``ElementWireContext`` and ``PlotSeries.decode_all``
    so a non-numeric size or a malformed series raises a typed ``ValueError``.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[PlotElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[PlotElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> PlotElement:
        """Construct a PlotElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("plot")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_id(raw),
            title=ctx.optional_str(raw, "title", default=""),
            x_label=ctx.optional_str(raw, "x_label", default=""),
            y_label=ctx.optional_str(raw, "y_label", default=""),
            width=ctx.optional_number(raw, "width", default=-1.0),
            height=ctx.optional_number(raw, "height", default=300.0),
            series=PlotSeries.decode_all(raw.get("series", []), "series"),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonPlotEncoder:
    """Encode a ``PlotElement`` to its JSON-compatible wire dict.

    Stateless. ``tooltip`` is omitted when absent; the remaining fields are
    always emitted.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: PlotElement) -> dict[str, object]:
        """Serialize a PlotElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "title": elem.title,
                "x_label": elem.x_label,
                "y_label": elem.y_label,
                "width": elem.width,
                "height": elem.height,
                "series": [series.to_dict() for series in elem.series],
                "tooltip": elem.tooltip,
            }
        )
