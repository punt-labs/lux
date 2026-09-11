"""HubScopedStore -- the aggregated-storage shape every multi-Hub collection uses.

An aggregated store is an object, not a dictionary passed between functions
(PY-OO-5, PY-IC-1). Two Hubs producing the identical local id could silently
clobber one another's entry in a bare dict; this class makes that collision
unrepresentable -- the real key is always a :class:`HubScopedKey`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub_scoped_key import HubScopedKey

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub_id import HubId

__all__ = ["HubScopedStore"]


@final
class HubScopedStore[V]:
    """The one aggregated-storage shape every Display-side multi-Hub
    collection composes, in place of a bare dict -- owns its own keying
    discipline; a caller never reaches past this class into a bare mapping.
    """

    _entries: dict[HubScopedKey, V]
    __slots__ = ("_entries",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._entries = {}
        return self

    def __len__(self) -> int:
        """Return how many entries this store holds, across every Hub."""
        return len(self._entries)

    def hub_count(self) -> int:
        """Return how many distinct Hubs currently hold an entry."""
        return len(self.hubs())

    def put(self, key: HubScopedKey, value: V) -> None:
        """Assign one entry; two collide only on an identical (hub, local)."""
        self._entries[key] = value

    def get(self, key: HubScopedKey) -> V | None:
        """Look up one entry; ``None`` answers a genuine "not present"."""
        return self._entries.get(key)

    def remove(self, key: HubScopedKey) -> V | None:
        """Remove and return one entry, or ``None`` if it was not present."""
        return self._entries.pop(key, None)

    def remove_all(self, local: str) -> list[V]:
        """Drop every Hub's entry for ``local`` -- for a caller with no live
        Hub to scope by, e.g. a Display-local closed tab."""
        stale = [key for key in self._entries if key.local == local]
        return [self._entries.pop(key) for key in stale]

    def remove_matching(self, local: str, value: V) -> list[HubScopedKey]:
        """Remove every entry whose local id and value both match -- the
        collision-safe :meth:`remove_all`. Returns the removed keys."""
        matches = [k for k in self.keys_for_value(value) if k.local == local]
        for key in matches:
            del self._entries[key]
        return matches

    def keys_for_value(self, value: V) -> list[HubScopedKey]:
        """Return every key currently mapped to ``value``, across every Hub."""
        return [key for key, v in self._entries.items() if v == value]

    def reassign_value(self, old: V, new: V, locals_filter: frozenset[str]) -> None:
        """Replace ``old`` with ``new`` for every entry whose local id is in
        ``locals_filter`` -- each entry's own Hub key is untouched, only its
        value moves. The ownership-transfer primitive a departed client's
        co-owned entries reassign through, scoped to one frame's scenes."""
        for key, value in list(self._entries.items()):
            if key.local in locals_filter and value == old:
                self._entries[key] = new

    def for_hub(self, hub: HubId) -> Iterator[tuple[str, V]]:
        """Every entry a given Hub currently owns, local id and value.

        The routing primitive a scene-less interaction or a menu click
        resolves its one target Hub through.
        """
        for key, value in self._entries.items():
            if key.hub == hub:
                yield key.local, value

    def entries(self) -> Iterator[tuple[HubScopedKey, V]]:
        """Every entry this store holds, across every Hub, with its full key.

        For a caller that owns this store privately and must resolve a bare
        local id to its owning entry (or entries) when the caller genuinely
        has no live Hub context -- a user gesture at the Display (closing a
        tab, Clear All), never a Hub-originated message. Scanning a Display's
        own in-process, small aggregated store is cheap; this does not leak
        the store's backing structure, only its logical contents.
        """
        yield from self._entries.items()

    def values(self) -> Iterator[V]:
        """Every value this store holds, across every Hub, key discarded."""
        return iter(self._entries.values())

    def hubs(self) -> frozenset[HubId]:
        """Return the distinct Hubs this store currently holds an entry for."""
        return frozenset(key.hub for key in self._entries)

    def flatten(self) -> dict[str, V]:
        """Merge every Hub's entries into one ``local -> value`` mapping.

        A genuine collision (two Hubs naming the identical local id)
        resolves last-write-wins here -- a caller-facing convenience for
        consumers with no live Hub to scope a read by, never the store's own
        collision-safe write path, which stays keyed by the full
        :class:`HubScopedKey`.
        """
        return {key.local: value for key, value in self._entries.items()}

    def purge_hub_not_in(self, hub: HubId, still_named: frozenset[str]) -> list[V]:
        """Drop every entry this Hub owns whose local id is absent from
        ``still_named``.

        The manifest-purge operation, scoped to one Hub's own entries by
        construction, so a second live Hub's entries are never candidates.
        """
        stale = [
            key
            for key in self._entries
            if key.hub == hub and key.local not in still_named
        ]
        return [self._entries.pop(key) for key in stale]

    def drop_hub(self, hub: HubId) -> list[V]:
        """Retire every entry a Hub owned, on disconnect."""
        stale = [key for key in self._entries if key.hub == hub]
        return [self._entries.pop(key) for key in stale]
