"""ImageElement — a bitmap / vector image on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. An image is a leaf — no children, no handlers, no
interaction — so it overrides none of the render-template hooks and inherits
the empty ``validate()`` default: its one structural invariant (a source that
is a path xor inline data) is established at construction, so a constructed
image is always valid.

The pixel source is a discriminated ``ImageSource`` (``PathImage`` xor
``DataImage``); the constructor resolves the ``path`` / ``data`` one-of at its
boundary and raises on "neither" or "both". Textures upload display-side through
``TextureCache`` — the renderer stays local; the element carries only the
serialized source.

The codec body lives in ``image_codec.py`` (``JsonImageEncoder`` /
``JsonImageDecoder``); ``to_dict`` and ``from_dict`` remain on the class as
short delegators so the runtime-checkable ``domain.element.Element`` Protocol
stays satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.image_codec import JsonImageDecoder, JsonImageEncoder
from punt_lux.protocol.elements.image_source import DataImage, ImageSource, PathImage
from punt_lux.protocol.elements.patch_field import PatchField

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["ImageElement", "ImageFormat"]

# The image encodings the renderer understands; ``None`` = infer from the source.
type ImageFormat = Literal["png", "jpeg", "svg"]


class ImageElement(Element):
    """An image to display, sourced from a path xor inline base64 data.

    PY-TS-14 OK: ``format`` / ``alt`` / ``width`` / ``height`` / ``tooltip`` are
    genuinely optional — ``format``/``alt``/``tooltip`` absent means the renderer
    infers or omits, and ``width``/``height`` absent means "natural pixel size".
    The path-xor-data one-of that *would* be two Optionals is instead the
    discriminated ``ImageSource`` (rule 5), so the source is never absent.
    """

    _id: str
    _source: ImageSource
    _format: ImageFormat | None
    _alt: str | None
    _width: int | None
    _height: int | None
    _tooltip: str | None
    _kind: Literal["image"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        path: str | None = None,
        data: str | None = None,
        format: ImageFormat | None = None,
        alt: str | None = None,
        width: int | None = None,
        height: int | None = None,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._source = cls._resolve_source(path, data)
        self._format = format
        self._alt = alt
        self._width = width
        self._height = height
        self._tooltip = tooltip
        self._kind = "image"
        return self

    @staticmethod
    def _resolve_source(path: str | None, data: str | None) -> ImageSource:
        """Return the one-of source, raising on "neither" or "both" (PY-CC-2).

        The discriminated invariant is established here so no constructed image
        can hold an absent or ambiguous source.
        """
        if path is not None and data is not None:
            msg = "ImageElement accepts 'path' or 'data', not both"
            raise ValueError(msg)
        if path is not None:
            return PathImage(path)
        if data is not None:
            return DataImage(data)
        msg = "ImageElement requires either 'path' or 'data'"
        raise ValueError(msg)

    @staticmethod
    def coerce_format(value: object) -> ImageFormat | None:
        """Return ``value`` as an ``ImageFormat`` (or ``None``), raising on unknown.

        A wire/patch ``format`` is one of the declared encodings, or absent
        (``None``); an unknown value is a boundary error (PY-EH-1), not a silent
        pass-through. Shared by the codec (through ``element_cls``) and the patch
        setter so both coerce the untyped value into the same Literal.
        """
        if value is None:
            return None
        if value in ("png", "jpeg", "svg"):
            return value
        msg = f"image element field 'format' must be one of png/jpeg/svg, got {value!r}"
        raise ValueError(msg)

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["image"]:
        """Return the wire discriminator — always ``"image"``."""
        return self._kind

    @property
    def source(self) -> ImageSource:
        """Return the discriminated pixel source (``PathImage`` xor ``DataImage``)."""
        return self._source

    @property
    def path(self) -> str | None:
        """Return the filesystem path, or ``None`` for a data-sourced image."""
        return self._source.path

    @property
    def data(self) -> str | None:
        """Return the base64 blob, or ``None`` for a path-sourced image."""
        return self._source.data

    @property
    def format(self) -> ImageFormat | None:
        """Return the declared encoding, or ``None`` to let the renderer infer."""
        return self._format

    @property
    def alt(self) -> str | None:
        """Return the alt text drawn when the texture cannot load."""
        return self._alt

    @property
    def width(self) -> int | None:
        """Return the render width in pixels, or ``None`` for the natural size."""
        return self._width

    @property
    def height(self) -> int | None:
        """Return the render height in pixels, or ``None`` for the natural size."""
        return self._height

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    def _set_path(self, value: object) -> None:
        """Switch to a path source (used by ``Element.apply_patch``)."""
        self._source = PathImage(PatchField("path").as_str(value))

    def _set_data(self, value: object) -> None:
        """Switch to a data source (used by ``Element.apply_patch``)."""
        self._source = DataImage(PatchField("data").as_str(value))

    def _set_format(self, value: object) -> None:
        """Replace the declared encoding, validating the Literal (PY-EH-1)."""
        self._format = self.coerce_format(value)

    def _set_alt(self, value: object) -> None:
        """Replace the alt text (used by ``Element.apply_patch``)."""
        self._alt = PatchField("alt").as_optional_str(value)

    def _set_width(self, value: object) -> None:
        """Replace the render width (used by ``Element.apply_patch``)."""
        self._width = PatchField("width").as_optional_int(value)

    def _set_height(self, value: object) -> None:
        """Replace the render height (used by ``Element.apply_patch``)."""
        self._height = PatchField("height").as_optional_int(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonImageEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct an ImageElement from a JSON-decoded mapping."""
        decoder = JsonImageDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the concrete subtype; the decoder's
        # annotation is the supertype, so narrow to ``Self`` for the Protocol.
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "path": self._source.path,
            "data": self._source.data,
            "format": self._format,
            "alt": self._alt,
            "width": self._width,
            "height": self._height,
            "tooltip": self._tooltip,
        }
