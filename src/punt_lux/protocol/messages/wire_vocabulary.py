"""WireVocabulary -- the set of message kinds one side of the wire may send."""

from __future__ import annotations

from typing import Self, final, get_args

from punt_lux.protocol.messages import DisplayMessage

__all__ = ["DISPLAY_VOCABULARY", "WireVocabulary"]


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

    def require(self, raw_type: object) -> None:
        """Raise ``ValueError`` unless ``raw_type`` is a tag in the vocabulary."""
        if not isinstance(raw_type, str) or raw_type not in self._tags:
            msg = f"message type {str(raw_type)[:40]!r} is not accepted on this stream"
            raise ValueError(msg)


# What a display may send the Hub: every ``DisplayMessage`` member's tag.
DISPLAY_VOCABULARY = WireVocabulary.of(DisplayMessage)
