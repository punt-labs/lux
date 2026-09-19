"""OwnerFactsCache and OwnerFactsStore — a frame's departure-guarded snapshot
of its owner's facts, and the keyed store that holds one per live frame.

The two classes are close collaborators, not an unrelated pair (PY-OO-2): the
store is a dict of frame_id -> cache, and its only job is picking the right
cache and pruning it when the frame it belongs to is gone.
"""

from __future__ import annotations

from typing import Self, final


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
    """One :class:`OwnerFactsCache` per live frame, keyed by frame id.

    Deliberately not a field on ``Frame`` (DES-c7xi round 2): the snapshot is
    Display-local bookkeeping the popup reads by id, not an aggregate-root
    concern -- keeping it here, in its own single-responsibility class, is
    what keeps ``Frame``'s cohesion from absorbing an unrelated field. An
    entry outlives nothing on its own; :meth:`prune` must be called when the
    frame it belongs to is disposed, or it leaks for the life of the process.
    """

    _by_frame: dict[str, OwnerFactsCache]
    __slots__ = ("_by_frame",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_frame = {}
        return self

    def adopt(
        self, frame_id: str, incoming: tuple[tuple[str, str], ...] | None
    ) -> None:
        """Adopt a push's owner facts for ``frame_id``, honoring the guarantee."""
        cache = self._by_frame.setdefault(frame_id, OwnerFactsCache())
        cache.update(incoming)

    def rows_for(self, frame_id: str) -> tuple[tuple[str, str], ...] | None:
        """Return ``frame_id``'s cached snapshot, or ``None`` if untracked."""
        cache = self._by_frame.get(frame_id)
        return cache.rows if cache is not None else None

    def prune(self, frame_id: str) -> None:
        """Drop ``frame_id``'s entry. A no-op if it holds none."""
        self._by_frame.pop(frame_id, None)
