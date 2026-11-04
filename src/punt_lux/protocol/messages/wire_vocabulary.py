"""WireVocabulary -- the set of message kinds one side of the wire may send."""

from __future__ import annotations

import logging
from typing import Any, Self, final, get_args

from punt_lux.protocol.messages import ClientMessage, DisplayMessage

logger = logging.getLogger(__name__)

__all__ = ["CLIENT_VOCABULARY", "DISPLAY_VOCABULARY", "WireVocabulary"]


@final
class WireVocabulary:
    """The wire ``type`` tags a peer is allowed to send.

    A reader checks the raw tag against the vocabulary before it decodes the
    frame, so a peer cannot make this side decode a kind it never sends.
    """

    _tags: frozenset[str]
    __slots__ = ("_tags",)

    def __new__(cls, tags: frozenset[str]) -> Self:
        self = super().__new__(cls)
        self._tags = tags
        return self

    @classmethod
    def of(cls, union: object) -> Self:
        """Return the vocabulary of every message class in a union of dataclasses."""
        return cls(
            frozenset(m.__dataclass_fields__["type"].default for m in get_args(union))
        )

    @property
    def tags(self) -> frozenset[str]:
        """The tags the vocabulary admits."""
        return self._tags

    def admitted(self, raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return the frames whose tag is in the vocabulary, skipping the rest.

        A skipped frame is never decoded; it is logged at WARNING with its tag
        and the stream carries on. The lenient counterpart of :meth:`require`.
        """
        kept: list[dict[str, Any]] = []
        for raw in raws:
            tag = raw.get("type")
            if isinstance(tag, str) and tag in self._tags:
                kept.append(raw)
            else:
                logger.warning("Skipping a frame of unknown type %s", str(tag)[:40])
        return kept

    def require(self, raw_type: object) -> None:
        """Raise ``ValueError`` unless ``raw_type`` is a tag in the vocabulary."""
        if not isinstance(raw_type, str) or raw_type not in self._tags:
            msg = f"message type {str(raw_type)[:40]!r} is not accepted on this stream"
            raise ValueError(msg)


# What a display may send the Hub: every ``DisplayMessage`` member's tag.
DISPLAY_VOCABULARY = WireVocabulary.of(DisplayMessage)
# What the Hub may send a display: every ``ClientMessage`` member's tag.
CLIENT_VOCABULARY = WireVocabulary.of(ClientMessage)
