"""HubScopedStore -- the aggregated-storage shape every multi-Hub collection uses.

An aggregated store is an object, not a dictionary passed between functions
(PY-OO-5, PY-IC-1). ``FrameBook``'s scene/frame maps and ``MenuReplica``'s
callback-menu map were, before this class existed, flat ``dict[str, ...]``
mappings spanning every connection the Display has ever seen -- a primitive
collection standing in for a domain type, with the keying and purge logic
living in whichever caller happened to touch the dict rather than on the
collection itself. Two Hubs producing the identical Rung-2 local id could
silently clobber one another's entry. This class makes that collision
unrepresentable: the real key is always a :class:`HubScopedKey`, so two
entries from different Hubs are never the same dict slot.
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
    """The one aggregated-storage shape every Display-side multi-Hub collection
    composes, in place of a bare dict.

    Owns its own keying discipline -- a caller never reaches past this class
    into a bare mapping -- and exposes only the operations an aggregator
    actually needs: assign, look up, remove one entry, enumerate one Hub's own
    entries or every entry, and retire one Hub's entries either wholesale
    (disconnect) or selectively (a manifest naming which of that Hub's own
    entries still exist). What structure backs this class is this class's
    own business and nobody else's; that encapsulation -- not any specific
    backing structure -- is the design-time commitment.
    """

    _entries: dict[HubScopedKey, V]
    __slots__ = ("_entries",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._entries = {}
        return self

    def put(self, key: HubScopedKey, value: V) -> None:
        """Assign one entry.

        Two entries collide only when they share the identical
        ``(hub, local)`` pair -- never across Hubs, by construction of the
        key type.
        """
        self._entries[key] = value

    def get(self, key: HubScopedKey) -> V | None:
        """Look up one entry.

        ``None`` answers a genuine "not present" -- there is no
        discriminated state hiding behind it.
        """
        return self._entries.get(key)

    def remove(self, key: HubScopedKey) -> V | None:
        """Remove and return one entry, or ``None`` if it was not present."""
        return self._entries.pop(key, None)

    def remove_all(self, local: str) -> list[V]:
        """Drop every Hub's entry for ``local``, regardless of which owns it.

        For a caller with no live Hub to scope a removal by -- a
        Display-local gesture (a closed tab), never a Hub-originated
        message -- matching :meth:`flatten`'s own any-Hub reach.
        """
        stale = [key for key in self._entries if key.local == local]
        return [self._entries.pop(key) for key in stale]

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
