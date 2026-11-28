"""The service operations' request models (DES-107).

A client registers the service it serves; any caller relays a typed request to a
provider. The relay core knows ``service``, ``operation`` and an opaque payload;
each service's own command classes know the typed request and reply and validate
before relaying.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from punt_lux.wire.operations.common import OpError

__all__ = ["RegisterServiceRequest", "RelayRequest"]

# A service name is a short token; a request naming none cannot reach a provider.
_NAME = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$")


class RegisterServiceRequest(BaseModel):
    """Register the service this connection serves, keyed by its declared host."""

    model_config = ConfigDict(frozen=True)

    service: str = _NAME

    @classmethod
    def parse(cls, service: str) -> RegisterServiceRequest | OpError:
        """Validate ``service``, or return an ``OpError`` instead of raising."""
        try:
            return cls(service=service)
        except ValidationError as exc:
            return OpError.from_validation(exc)


class RelayRequest(BaseModel):
    """A typed request for the provider of ``service`` on ``host``.

    An omitted ``host`` is the Hub's own host: one rule, with no behavior that
    depends on how many providers exist.
    """

    model_config = ConfigDict(frozen=True)

    service: str = _NAME
    operation: str = _NAME
    # The operation's request; a wire boundary, typed models at both ends.
    payload: dict[str, object] = Field(default_factory=dict)
    host: str | None = None  # absent means the Hub's own host (DES-107 decision 5)
