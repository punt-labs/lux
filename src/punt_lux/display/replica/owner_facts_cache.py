"""OwnerFactsCache and OwnerFactsStore — a frame's departure-guarded snapshot
of its owner's facts, and the keyed store that holds one per live frame.

The two classes are close collaborators, not an unrelated pair (PY-OO-2): the
store is a dict of ``HubScopedKey`` -> cache, and its only job is picking the
right cache and pruning it when the frame it belongs to is gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.identity import HubScopedKey


@final
class OwnerFactsCache:
    """The last-known owner facts for one frame, held across departures.

    A push carrying rows adopts them; a push carrying ``None`` -- the owner
    departed, or the Hub could not resolve it -- leaves the cached snapshot
    untouched (the departure guarantee). The guard lives here, on the data it
    protects, rather than in the caller that decides whether to write.
    """

    _rows: tuple[tuple[str, str], ...] | None
    __slots__ = ("_rows",)

    def __new__(cls, rows: tuple[tuple[str, str], ...] | None = None) -> Self:
        self = super().__new__(cls)
        self._rows = rows
        return self

    @property
    def rows(self) -> tuple[tuple[str, str], ...] | None:
        """Return the cached snapshot, or ``None`` if never populated."""
        return self._rows

    def update(self, incoming: tuple[tuple[str, str], ...] | None) -> None:
        """Adopt ``incoming`` unless it is ``None`` -- the departure guarantee."""
        if incoming is not None:
            self._rows = incoming


@final
class OwnerFactsStore:
    """One :class:`OwnerFactsCache` per live frame, keyed by ``HubScopedKey``.

    Deliberately not a field on ``Frame`` (DES-c7xi round 2): the snapshot is
    Display-local bookkeeping the popup reads by id, not an aggregate-root
    concern -- keeping it here, in its own single-responsibility class, is
    what keeps ``Frame``'s cohesion from absorbing an unrelated field.

    Keyed by ``HubScopedKey`` -- a bare frame id, not the ``(hub, frame_id)``
    pair -- would collide when two Hubs mint the identical frame id (e.g. both
    naming a frame "main"), exactly the collision ``FrameBook``/
    ``HubScopedStore`` already guard against for the frame itself. An entry
    outlives nothing on its own; :meth:`prune` must be called when the frame
    it belongs to is disposed, or it leaks for the life of the process --
    and only that Hub's entry, never a same-named sibling's.
    """

    _by_key: dict[HubScopedKey, OwnerFactsCache]
    __slots__ = ("_by_key",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_key = {}
        return self

    def adopt(
        self, key: HubScopedKey, incoming: tuple[tuple[str, str], ...] | None
    ) -> None:
        """Adopt a push's owner facts for ``key``, honoring the guarantee."""
        cache = self._by_key.setdefault(key, OwnerFactsCache())
        cache.update(incoming)

    def rows_for(self, key: HubScopedKey) -> tuple[tuple[str, str], ...] | None:
        """Return ``key``'s cached snapshot, or ``None`` if untracked."""
        cache = self._by_key.get(key)
        return cache.rows if cache is not None else None

    def prune(self, key: HubScopedKey) -> None:
        """Drop ``key``'s entry. A no-op if it holds none."""
        self._by_key.pop(key, None)

    def clear(self) -> None:
        """Drop every entry -- the owner-facts half of a Clear All."""
        self._by_key.clear()
