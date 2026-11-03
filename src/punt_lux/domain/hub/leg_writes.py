"""Registration and Detachment -- what a callback write or a teardown did.

Each pairs the outcome the caller branches on with the registry write behind it,
so the lifecycle step that made the write can settle what it owes the Hub
without reading the registry a second time. A write that was refused or found
nothing to do has no write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_listing import PresenceChange
    from punt_lux.domain.hub.registry_outcomes import (
        CallbackRegistration,
        ListenerDetachment,
    )
    from punt_lux.domain.hub.session_callback import SessionCallback
    from punt_lux.domain.hub.session_write import SessionWrite

__all__ = ["Detachment", "Registration"]


@final
@dataclass(frozen=True, slots=True)
class Registration:
    """What registering a callback did, and the write that took it.

    Only a registration that took has a write, and construction checks that: a
    ``registered`` outcome carries one, any refusal carries none. :meth:`took`
    also checks that the stored session holds the callback it was made to store.
    """

    outcome: CallbackRegistration
    # None: the registration was refused, so the registry was not written.
    write: SessionWrite | None

    def __post_init__(self) -> None:
        if (self.outcome == "registered") != (self.write is not None):
            msg = f"a {self.outcome!r} registration and its write disagree"
            raise ValueError(msg)

    @classmethod
    def took(cls, write: SessionWrite, callback: SessionCallback) -> Self:
        """A registration the registry accepted: its write, which stored ``callback``.

        Raises ``ValueError`` if the write's session does not hold ``callback``.
        """
        if callback not in write.after.callbacks:
            msg = f"a registered write did not store the callback {callback.id!r}"
            raise ValueError(msg)
        return cls("registered", write)

    @classmethod
    def refused(cls, outcome: Literal["superseded", "declined"]) -> Self:
        """A registration the registry did not write, and why."""
        return cls(outcome, None)

    @property
    def presence(self) -> PresenceChange:
        """How the write changed who the Clients menu lists; ``unchanged`` if none."""
        return "unchanged" if self.write is None else self.write.presence


@final
@dataclass(frozen=True, slots=True)
class Detachment:
    """What a teardown found and released, and the write that released it.

    Built through :meth:`released` or :meth:`nothing`: a release derives its
    outcome from the write it made, so the two cannot disagree.
    """

    outcome: ListenerDetachment
    # None: nothing was released -- the session was gone, or a successor holds it.
    write: SessionWrite | None

    def __post_init__(self) -> None:
        write = self.write
        if write is None:
            agrees = self.outcome in ("kept", "released_with_session")
        else:
            agrees = self.outcome == self._released_outcome(write)
        if not agrees:
            msg = f"a {self.outcome!r} detachment and its write disagree"
            raise ValueError(msg)

    @classmethod
    def released(cls, write: SessionWrite) -> Self:
        """A release: it carried the callbacks off with it if the session held any."""
        return cls(cls._released_outcome(write), write)

    @staticmethod
    def _released_outcome(write: SessionWrite) -> ListenerDetachment:
        """What a release is called: the one place it is decided, from its write."""
        held = write.before is not None and bool(write.before.callbacks)
        return "released_with_callbacks" if held else "released"

    @classmethod
    def nothing(cls, outcome: Literal["kept", "released_with_session"]) -> Self:
        """A teardown that released nothing: a successor holds the slot, or none."""
        return cls(outcome, None)

    @property
    def presence(self) -> PresenceChange:
        """How the write changed who the Clients menu lists; ``unchanged`` if none."""
        return "unchanged" if self.write is None else self.write.presence
