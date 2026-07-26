"""PlotElement — a display-only 2D chart on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. A plot is a leaf: its ``series`` are a typed ``PlotSeries``
value family (no more ``list[dict]``), not child elements, so it overrides none
of the render-template hooks and its children walk is empty.

Validation is split by the kind of fault it guards, closing the named defect
that a malformed series raised through the render loop and took the display
down. A type fault — a non-string label or a non-numeric coordinate — is
rejected at the wire boundary by ``PlotSeries.decode_all`` (PY-EH-1), before any
PlotElement exists. The one invariant a typed series can still hold — ``x`` and
``y`` of unequal length — is a semantic fault ``validate`` reports, so every
ragged series in a tree surfaces at once. The renderer keeps its own label
``TypeError`` guard as defense-in-depth.

The codec body lives in ``plot_codec.py``; ``to_dict`` and ``from_dict`` remain
short delegators so the ``domain.element.Element`` Protocol stays satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.plot_codec import JsonPlotDecoder, JsonPlotEncoder
from punt_lux.protocol.elements.plot_series import PlotSeries

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["PlotElement"]


class PlotElement(Element):
    """A 2D plot of one or more typed ``PlotSeries`` (line, scatter, bar).

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``title``/``x_label``/``y_label`` are total ``str``
    (default ``""``), ``width``/``height`` total ``float`` (``-1`` fills the
    available width), and ``series`` a total tuple, so none needs an Optional.
    """

    _id: str
    _title: str
    _x_label: str
    _y_label: str
    _width: float
    _height: float
    _series: tuple[PlotSeries, ...]
    _tooltip: str | None
    _kind: Literal["plot"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        title: str = "",
        x_label: str = "",
        y_label: str = "",
        width: float = -1.0,
        height: float = 300.0,
        series: tuple[PlotSeries, ...] = (),
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._title = title
        self._x_label = x_label
        self._y_label = y_label
        self._width = width
        self._height = height
        self._series = series
        self._tooltip = tooltip
        self._kind = "plot"
        return self

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["plot"]:
        """Return the wire discriminator — always ``"plot"``."""
        return self._kind

    @property
    def title(self) -> str:
        """Return the plot's title, or ``""`` for no title."""
        return self._title

    @property
    def x_label(self) -> str:
        """Return the x-axis label, or ``""`` for none."""
        return self._x_label

    @property
    def y_label(self) -> str:
        """Return the y-axis label, or ``""`` for none."""
        return self._y_label

    @property
    def width(self) -> float:
        """Return the plot width in pixels (``-1`` fills the available width)."""
        return self._width

    @property
    def height(self) -> float:
        """Return the plot height in pixels."""
        return self._height

    @property
    def series(self) -> tuple[PlotSeries, ...]:
        """Return the data series, each a typed ``PlotSeries`` value."""
        return self._series

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    def validate(self) -> tuple[ValidationError, ...]:
        """Return one error per series whose ``x`` and ``y`` lengths differ.

        A ragged series is the one malformation a typed ``PlotSeries`` can still
        carry; every offending series is reported so the agent fixes them all at
        once, and none reaches the renderer to fault mid-draw.
        """
        return tuple(
            ValidationError(
                self._id,
                self._kind,
                f"series[{i}] {s.label!r}: x has {len(s.x)} points, y has {len(s.y)}",
            )
            for i, s in enumerate(self._series)
            if s.is_ragged
        )

    def _set_title(self, value: object) -> None:
        """Replace the title (used by ``Element.apply_patch``)."""
        self._title = PatchField("title").as_str(value)

    def _set_x_label(self, value: object) -> None:
        """Replace the x-axis label (used by ``Element.apply_patch``)."""
        self._x_label = PatchField("x_label").as_str(value)

    def _set_y_label(self, value: object) -> None:
        """Replace the y-axis label (used by ``Element.apply_patch``)."""
        self._y_label = PatchField("y_label").as_str(value)

    def _set_width(self, value: object) -> None:
        """Replace the width (used by ``Element.apply_patch``)."""
        self._width = PatchField("width").as_number(value)

    def _set_height(self, value: object) -> None:
        """Replace the height (used by ``Element.apply_patch``)."""
        self._height = PatchField("height").as_number(value)

    def _set_series(self, value: object) -> None:
        """Replace the series, rejecting a malformed one (``Element.apply_patch``)."""
        self._series = PlotSeries.decode_all(value, "series")

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonPlotEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a PlotElement from a JSON-decoded mapping."""
        decoder = JsonPlotDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the concrete subtype; the decoder's
        # annotation is the supertype, so narrow to ``Self`` for the Protocol.
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "title": self._title,
            "x_label": self._x_label,
            "y_label": self._y_label,
            "width": self._width,
            "height": self._height,
            "series": [series.to_dict() for series in self._series],
            "tooltip": self._tooltip,
        }
