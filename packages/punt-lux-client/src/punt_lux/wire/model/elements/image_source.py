"""ImageSource — the discriminated source of an image's pixels.

An image is sourced by *exactly one* of a filesystem ``path`` or an inline
base64 ``data`` blob — never both, never neither. Rather than carry two
``str | None`` fields and a runtime check (the shape the legacy dataclass had),
the source is a discriminated pair: ``PathImage`` xor ``DataImage``. The illegal
"both" and "neither" states are unrepresentable once a source is constructed
(PY-TS-14, rule 5); ``ImageElement`` resolves the one-of at its boundary and
holds a single ``ImageSource`` thereafter.

Each variant answers the same messages (rule 2 — a family shares by Protocol,
not a base class): ``path`` and ``data`` project the one-of as the two
``str | None`` accessors the renderer and wire need, ``wire`` emits the single
key that variant owns, and ``load_texture`` dispatches to the right loader leg so
the renderer never branches on path-vs-data.
"""

from __future__ import annotations

from typing import Protocol, Self, final, runtime_checkable

__all__ = ["DataImage", "ImageSource", "PathImage", "TextureLoader"]


@runtime_checkable
class TextureLoader(Protocol):
    """A cache that turns an image source into an uploaded texture id.

    Declared here (not in the display layer) so ``ImageSource`` can name the
    collaborator without a protocol-to-display import; the Display's
    ``TextureCache`` satisfies it structurally.
    """

    def get_or_load(self, path: str) -> int | None:
        """Return a texture id for a filesystem *path*, or ``None`` on failure."""
        ...

    def get_or_load_data(self, data: str) -> int | None:
        """Return a texture id for a base64 *data* blob, or ``None`` on failure."""
        ...


@runtime_checkable
class ImageSource(Protocol):
    """One-of an image's pixel source: a filesystem path or inline base64 data."""

    @property
    def path(self) -> str | None:
        """Return the filesystem path, or ``None`` for a data-sourced image."""
        ...

    @property
    def data(self) -> str | None:
        """Return the base64 blob, or ``None`` for a path-sourced image."""
        ...

    def wire(self) -> dict[str, str]:
        """Return the single wire key this variant owns (``path`` or ``data``)."""
        ...

    def load_texture(self, loader: TextureLoader) -> int | None:
        """Resolve this source to a texture id through *loader* (dispatch on kind).

        Polymorphism over a conditional: each variant knows which loader leg it
        uses, so the renderer asks the source instead of branching on path-vs-data.
        """
        ...


@final
class PathImage:
    """An image sourced from a filesystem ``path``."""

    _path: str
    __slots__ = ("_path",)

    def __new__(cls, path: str) -> Self:
        self = super().__new__(cls)
        self._path = path
        return self

    def __getnewargs__(self) -> tuple[str]:
        """Return the ``__new__`` args so the pickle wire can reconstruct it.

        A slotted class with a required positional ``__new__`` arg cannot be
        rebuilt by the default ``cls.__new__(cls)`` — an ImageElement crosses
        the Hub→Display boundary as a pickled tree, and its source is part of
        that pickled state.
        """
        return (self._path,)

    @property
    def path(self) -> str | None:
        """Return the filesystem path this image loads from."""
        return self._path

    @property
    def data(self) -> str | None:
        """Return ``None`` — a path-sourced image carries no inline data."""
        return None

    def wire(self) -> dict[str, str]:
        """Return the ``path`` wire key."""
        return {"path": self._path}

    def load_texture(self, loader: TextureLoader) -> int | None:
        """Load this path through the cache's path leg."""
        return loader.get_or_load(self._path)


@final
class DataImage:
    """An image sourced from an inline base64 ``data`` blob."""

    _data: str
    __slots__ = ("_data",)

    def __new__(cls, data: str) -> Self:
        self = super().__new__(cls)
        self._data = data
        return self

    def __getnewargs__(self) -> tuple[str]:
        """Return the ``__new__`` args so the pickle wire can reconstruct it.

        A slotted class with a required positional ``__new__`` arg cannot be
        rebuilt by the default ``cls.__new__(cls)`` — an ImageElement crosses
        the Hub→Display boundary as a pickled tree, and its source is part of
        that pickled state.
        """
        return (self._data,)

    @property
    def path(self) -> str | None:
        """Return ``None`` — a data-sourced image carries no filesystem path."""
        return None

    @property
    def data(self) -> str | None:
        """Return the base64 blob this image renders from."""
        return self._data

    def wire(self) -> dict[str, str]:
        """Return the ``data`` wire key."""
        return {"data": self._data}

    def load_texture(self, loader: TextureLoader) -> int | None:
        """Decode this base64 blob through the cache's data leg."""
        return loader.get_or_load_data(self._data)
