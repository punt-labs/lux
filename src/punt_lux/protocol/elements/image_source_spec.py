"""ImageSourceSpec — the wire one-of (path xor data) before it is an ImageSource.

An image arrives from the wire as two nullable fields, ``path`` and ``data``, of
which exactly one must be present. This value object holds that raw one-of and
resolves it to the discriminated ``ImageSource`` (``PathImage`` xor
``DataImage``), raising on the two illegal shapes — "neither" and "both" — so a
constructed image can never hold an absent or ambiguous source (PY-CC-2, rule 5).
Modelling the one-of as its own type keeps the resolution beside the family it
produces rather than loose inside the element constructor.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.protocol.elements.image_source import DataImage, ImageSource, PathImage

__all__ = ["ImageSourceSpec"]


@final
class ImageSourceSpec:
    """The raw ``path``/``data`` one-of, resolvable to a discriminated source."""

    _path: str | None
    _data: str | None
    __slots__ = ("_data", "_path")

    def __new__(cls, path: str | None, data: str | None) -> Self:
        self = super().__new__(cls)
        self._path = path
        self._data = data
        return self

    def resolve(self) -> ImageSource:
        """Return the discriminated source, raising on "neither" or "both"."""
        if self._path is not None:
            if self._data is not None:
                msg = "ImageElement accepts 'path' or 'data', not both"
                raise ValueError(msg)
            return PathImage(self._path)
        if self._data is not None:
            return DataImage(self._data)
        msg = "ImageElement requires either 'path' or 'data'"
        raise ValueError(msg)
