"""The ``Capability`` vocabulary — wire behaviours a kind's decoder can carry.

A single-source enum so the capability-parity guard and every spec name the same
tags. A typo (``HANDLER`` for ``HANDLERS``) becomes an import-time
``AttributeError`` — fail-loud — instead of a silently-defeated capability check,
which a bare ``str`` tag would allow.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Capability"]


class Capability(StrEnum):
    """A wire behaviour a built decoder carries, checked by ``AbcKindVerifier``.

    ``HANDLERS`` — the decoder wires interaction-event handlers. ``PRE_DECODE`` —
    the decoder canonicalizes wire sugar (Button's click/publish) before decode.
    """

    HANDLERS = "handlers"
    PRE_DECODE = "pre_decode"
