"""Parse a ``GET /display/link`` reply into its discriminated shape.

A 2xx body parses straight into ``ConnectedLinkState``/``DisconnectedLinkState``
via one discriminated-union adapter; anything else (a non-2xx status, or a
malformed 2xx body) falls through to :class:`RestReply`'s own status/error
table, reusing the same mapping every other read shares.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Self, final

from pydantic import Field, TypeAdapter, ValidationError

from punt_lux.operations.models.display_link import (
    ConnectedLinkState,
    DisconnectedLinkState,
)
from punt_lux.rest_reply import RestReply

if TYPE_CHECKING:
    from punt_lux.operations import OpError
    from punt_lux.operations.models.display_link import DisplayLinkState
    from punt_lux.rest_transport import HttpResponse

__all__ = ["LinkReply"]

_LinkAdapter: TypeAdapter[DisplayLinkState] = TypeAdapter(
    Annotated[ConnectedLinkState | DisconnectedLinkState, Field(discriminator="kind")]
)


@final
class LinkReply:
    """Reads one ``GET /display/link`` HTTP response into its typed shape."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def read(response: HttpResponse) -> DisplayLinkState | OpError:
        """Return the parsed link state, or the mapped ``OpError``."""
        try:
            return _LinkAdapter.validate_json(response.body)
        except ValidationError:
            return RestReply(response).read(ConnectedLinkState)
