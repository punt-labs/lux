"""MirrorState — the display-side element-mirror check as a discriminated state.

Proxied from the running display, never read as Hub authority
(introspection-api.md). The three arms keep "you didn't ask"
(``not_requested``), "you asked and I couldn't tell" (``unavailable``), and "here
is the answer" (``present``) from ever being confused — the same shape the
painted-geometry state uses, kept in its own module so ``SceneInspection``
composes one mirror concern and one geometry concern rather than housing both.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "MirrorNotRequested",
    "MirrorPresent",
    "MirrorState",
    "MirrorUnavailable",
]


class MirrorNotRequested(BaseModel):
    """The caller did not ask for the display-side mirror check."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["not_requested"] = "not_requested"


class MirrorUnavailable(BaseModel):
    """The mirror check was requested but could not be answered.

    A display that is down, a timed-out round-trip, or a malformed reply — the
    ``reason`` carries which. Distinct from ``not_requested`` so a caller can tell
    "you didn't ask" from "you asked and I couldn't tell".
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["unavailable"] = "unavailable"
    reason: str


class MirrorPresent(BaseModel):
    """The mirror check was answered: whether every element is mirrored.

    ``present`` is the whole-scene answer — true only when the display holds a
    mirror for every element, since a partially-mirrored scene is not present. An
    empty scene is vacuously present (no element is unmirrored) — an intentional
    edge, since the absent-scene case is a ``not_found`` error returned before the
    check runs. Never read as Hub authority (introspection-api.md).
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["present"] = "present"
    present: bool


# The display-side mirror check as a discriminated state, so "not requested",
# "requested but unavailable", and "answered" can never be confused.
MirrorState = Annotated[
    MirrorNotRequested | MirrorUnavailable | MirrorPresent,
    Field(discriminator="kind"),
]
