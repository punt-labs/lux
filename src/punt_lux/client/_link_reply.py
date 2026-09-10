"""Parse a ``GET /display/link`` reply into its discriminated shape.

A 2xx body decodes via one discriminated-union adapter; anything else falls
through to :class:`RestReply`'s shared status/error table.
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
        is_2xx = 200 <= response.status < 300
        try:
            return _LinkAdapter.validate_json(response.body if is_2xx else b"")
        except ValidationError:
            # ConnectedLinkState is just the error-extraction vehicle here.
            return RestReply(response).read(ConnectedLinkState)
