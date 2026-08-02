"""HeaderValue — one ``X-Lux-Client-*`` value, in both wire directions.

A header value has to survive two transports that do not agree about anything but
ASCII. The WebSocket client encodes header values as UTF-8; the HTTP client encodes
them as latin-1; the server decodes both as latin-1. Give either one the same
non-ASCII name and the server reads two different strings — and that string is what
the connection id hashes, so one session's two legs land on two connections and a
callback registered over REST becomes invisible to the WebSocket that was supposed
to receive its clicks. The menu entry never appears and nothing reports an error.

This class closes the gap from both ends, so the Hub reads one name from both legs
whether or not the client knows to encode:

* **On the way out**, a value is percent-encoded, so it is ASCII on either
  transport. Every printable ASCII character but ``%`` is left alone, so values
  that were already ASCII cross byte-for-byte as they always did.
* **On the way in**, a value that arrived as raw bytes — from an older punt-lux, or
  any client that does not use :class:`~punt_lux.identity_headers.ClientHeaders` —
  is recovered. Bytes the server decoded as latin-1 that spell valid UTF-8 are
  re-read as UTF-8: that is exactly the WebSocket leg's case, while the HTTP leg's
  latin-1 bytes do not spell valid UTF-8 and are kept as they are. The encoding
  side alone could not fix this, because it only governs clients we ship.

The recovery reads an ambiguous value as UTF-8, which is what a client sending raw
bytes means today. A latin-1 value whose bytes happen to spell valid UTF-8 (a name
containing a literal ``Ã©``) is read as the character that pair encodes.
"""

from __future__ import annotations

from typing import Self, final
from urllib.parse import quote, unquote

__all__ = ["HeaderValue"]

# What the encoding leaves alone: every printable ASCII character except ``%``,
# which is encoded so a value containing one still round-trips.
_WIRE_SAFE = " !\"#$&'()*+,-./:;<=>?@[\\]^_`{|}~"


@final
class HeaderValue:
    """One identity header value: the text it means, and the ASCII it crosses as."""

    _text: str
    __slots__ = ("_text",)

    def __new__(cls, text: str) -> Self:
        self = super().__new__(cls)
        self._text = text
        return self

    @classmethod
    def sent(cls, value: str | None) -> str:
        """The header text for ``value``, or ``""`` for a field the client omits.

        A blank header equals no header on the read side, so one absence spelling
        serves both: a caller renders every field and drops the blanks.
        """
        return "" if value is None else cls(value).to_wire()

    @classmethod
    def declared(cls, raw: str) -> str:
        """The text a header declares, or ``""`` when it declares nothing.

        The read counterpart of :meth:`sent`: a missing header, a blank one, and a
        whitespace-only one all mean the client declared no such field.
        """
        return cls.from_wire(raw).text.strip()

    @classmethod
    def from_wire(cls, raw: str) -> Self:
        """Read a header value the server decoded as latin-1 back into its text.

        Two corrections, in the order the value acquired them: the transport's
        byte interpretation is recovered first, then the percent-encoding this
        class applies on the way out is undone. A value that crossed as ASCII —
        every value one of our own clients sends — is unchanged by the first step.
        """
        return cls(unquote(cls._as_the_client_sent_it(raw)))

    @staticmethod
    def _as_the_client_sent_it(raw: str) -> str:
        """Re-read latin-1-decoded bytes as UTF-8 when that is what they spell.

        The one place the two transports are reconciled. A WebSocket client's UTF-8
        bytes reach here as mojibake (``Â·`` for ``·``) and are recovered; an HTTP
        client's latin-1 bytes do not form valid UTF-8 and are returned untouched.
        Both are wire input, so a value that decodes as neither is kept rather than
        rejected — a garbled name is an attribution the user can see and correct,
        not grounds to refuse the connection.
        """
        try:
            return raw.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return raw

    @property
    def text(self) -> str:
        """The value as the client meant it, non-ASCII characters and all."""
        return self._text

    def to_wire(self) -> str:
        """Render this value as the ASCII a header carries unambiguously."""
        return quote(self._text, safe=_WIRE_SAFE)
